#!/usr/bin/env python3
"""One-shot G3 source upload window runner; Python stdlib only.

The runner is fail-closed.  It has no resume/retry path: every mutating HTTP
request is durably marked STARTED before one send, and any ambiguous result
stops the entire sequence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.client
import json
import os
import secrets
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


WORKTREE = Path("/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation")
EVIDENCE = WORKTREE / "docs/insurance-kb/evidence/830-g3"
TENANT_ID = 10003
RAW_KB_ID = "b1f1764c-443d-46b8-98e3-d5aa5e55eb42"
MODEL_ID = "42df7f04-f53f-42d5-909d-63b0e78a1223"
APP = "weknora-g3-830-app"
DOCREADER = "weknora-g3-830-docreader"
REDIS = "weknora-g3-830-redis"
INTERNAL_NETWORK = "weknora-g3-830-internal"
EGRESS_NETWORK = "weknora-g3-830-upload-egress"
API_ORIGIN = "http://127.0.0.1:18294"
GUARD_BASE_URL = "http://127.0.0.1:19030/compatible-mode/v1"
MANIFEST_SHA256 = "75b40ece28a4219965a6a86be616bb90f17af53252afad6c2243dedb9e377225"
GUARD_SHA256 = "c52cfabf9f32214923e71e2f5926cb66c259cec9e99431033c508907aa7361a4"
PROVISION_SHA256 = "823008da91db113633a894bccd8cd88ec8559cc5ed43032728bc18639e83b2e4"
CORPUS_SHA256 = "3260b23abec9740cc7cbed161273922a3c7a63771fe60fc4cbad013f481a9753"
OFFLINE_PLAN_SHA256 = "553abd2ae85c39c62d6792265edee08a3d78f9eed663e067d6ffacf3b1e171b3"
RUNTIME_PREFLIGHT_SHA256 = "3d8fff08813ccbc2e9f437132644c5a39be2f60e69dfe5de598caf5187cd0765"
APP_IMAGE = "sha256:600a5a1cf93f4d2ecbe5466b7733c8d82395cdcad99fb501fb50ddf224220b19"
DOCREADER_IMAGE = "sha256:ac944d934fcd30c77e4ff28d19f1b4d6dd147012a6553c4678274c1f0be35868"
REDIS_IMAGE = "sha256:02f2cc4882f8bf87c79a220ac958f58c700bdec0dfb9b9ea61b62fb0e8f1bfcf"
PG_CONTAINER = "WeKnora-p0-clone-postgres-vsnd11r2"
PG_IMAGE = "sha256:af585013f97f622715de01e48d00558f7edf17055d7b40deafc9f98ca8d99a56"
TARGET_DB = "weknora_g3_830"
DB_USER = "p0clone"
MATERIAL_IDS = tuple(f"g3-material-{n:02d}" for n in (7, 8, 9, 11, 12, 13, 14, 17, 18, 19, 21))
OLD_KNOWLEDGE_IDS = {
    "g3-material-01": "f987fc16-222a-4246-8ca0-22c1a81dd6d9",
    "g3-material-02": "1265a343-c408-4620-8eed-c4f6a2adadc2",
    "g3-material-03": "5ad208d2-a9a1-4b66-a292-45ab06cb10c8",
    "g3-material-04": "e7722140-3486-437b-9952-f3d66d6fb539",
}
OLD_SOURCE_IDS = {
    "g3-material-01": "ea7160149d2fd99ea4a4960c50bfa6ca3641e4532956671b9956f4f8b57ad681",
    "g3-material-03": "d82d39ff488f8965b62bb9cb1bb5f147b6690617ba1c45a06ce9ea37659c7cd3",
    "g3-material-04": "aed62bb6045daf632084f85970244cb840a2ea81932d3620bfa4efb1a4a03d0e",
}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def file_md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def regular_file(path: Path, expected_sha: str | None = None) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError(f"not an exact regular file: {path}")
    raw = path.read_bytes()
    if expected_sha and sha256_bytes(raw) != expected_sha:
        raise RuntimeError(f"frozen input drift: {path}")
    return raw


def secret_line(path: Path, *, trim_outer_space: bool) -> str:
    raw = regular_file(path)
    if stat.S_IMODE(path.lstat().st_mode) & 0o077:
        raise RuntimeError("secret file permissions must exclude group/other")
    if b"\x00" in raw or b"\r" in raw.rstrip(b"\r\n") or b"\n" in raw.rstrip(b"\r\n"):
        raise RuntimeError("secret file must contain one line")
    value = raw.decode("utf-8").rstrip("\r\n")
    return value.strip() if trim_outer_space else value


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def atomic_json(path: Path, value: Any, *, exclusive: bool = False) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            raw = canonical(value) + b"\n"
            while raw:
                raw = raw[os.write(fd, raw):]
            os.fsync(fd)
        finally:
            os.close(fd)
    else:
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            raw = canonical(value) + b"\n"
            while raw:
                raw = raw[os.write(fd, raw):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


@dataclass(frozen=True)
class Material:
    material_id: str
    filename: str
    size: int
    md5: str
    sha256: str
    pages: int
    request_sha256: str = ""
    path: Path | None = None


@dataclass(frozen=True)
class FrozenInputs:
    materials: tuple[Material, ...]
    old_materials: dict[str, Material]
    process_config: dict[str, Any]
    manifest_sha256: str
    old_descriptors: dict[str, dict[str, Any]]


def expected_process_config() -> dict[str, Any]:
    return {
        "parser_engine_rules": [{"file_types": ["pdf"], "engine": "builtin"}],
        "parser_engine_overrides": {"pdf_native_structure_capture": "builtin-pdfium-charbox-v1"},
        "chunking_config": {
            "strategy": "legacy", "chunk_size": 2048, "chunk_overlap": 80,
            "separators": ["\n\n", "\n", "。"], "enable_parent_child": False,
        },
        "enable_multimodel": False,
        "graph_enabled": False,
        "question_generation_config": {"enabled": False, "question_count": 0},
    }


def expected_persisted_process_overrides() -> dict[str, Any]:
    """Exact Go JSON readback; ChunkingConfig false uses its declared omitempty."""
    value = expected_process_config()
    del value["chunking_config"]["enable_parent_child"]
    return value


def load_frozen_inputs(root: Path) -> FrozenInputs:
    evidence = root / "docs/insurance-kb/evidence/830-g3"
    corpus_raw = regular_file(evidence / "corpus-files-v4.json", CORPUS_SHA256)
    offline_raw = regular_file(evidence / "offline-embedding-preparation-plan.json", OFFLINE_PLAN_SHA256)
    manifest_raw = regular_file(evidence / "embedding-transport-manifest.json", MANIFEST_SHA256)
    runtime_raw = regular_file(evidence / "runtime-readonly-preflight.json", RUNTIME_PREFLIGHT_SHA256)
    guard_path = evidence / "embedding_guard.py"
    regular_file(guard_path, GUARD_SHA256)
    corpus = json.loads(corpus_raw)
    offline = json.loads(offline_raw)
    manifest = json.loads(manifest_raw)
    runtime_preflight = json.loads(runtime_raw)
    if offline.get("process_config") != expected_process_config():
        raise RuntimeError("offline process config drift")
    requests = manifest.get("requests")
    if (manifest.get("contract") != "830-g3-prepared-embedding-transport.v1"
            or manifest.get("provider_calls") != 0 or manifest.get("batch_embed_size") != 100
            or not isinstance(requests, list) or len(requests) != 11):
        raise RuntimeError("transport manifest must contain exact eleven")
    if [row.get("material_id") for row in requests] != list(MATERIAL_IDS):
        raise RuntimeError("transport request ordering drift")
    request_by_id = {row.get("material_id"): row for row in requests}
    entry_by_id = {row.get("inventory_id"): row for row in corpus.get("entries", [])}
    if tuple(sorted(request_by_id)) != MATERIAL_IDS or any(mid not in entry_by_id for mid in MATERIAL_IDS):
        raise RuntimeError("material membership/order drift")
    materials = []
    for mid in MATERIAL_IDS:
        entry, request = entry_by_id[mid], request_by_id[mid]
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("source path escapes root")
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise RuntimeError("source path escapes root")
        raw = regular_file(path)
        if len(raw) != entry["size_bytes"] or sha256_bytes(raw) != entry["file_sha256"]:
            raise RuntimeError(f"source bytes drift: {mid}")
        request_path = root / request["persisted_path"]
        request_raw = regular_file(request_path, request["request_sha256"])
        if len(request_raw) != request["body_bytes"] or request["source_sha256"] != entry["file_sha256"]:
            raise RuntimeError(f"request binding drift: {mid}")
        materials.append(Material(mid, path.name, len(raw), file_md5(path), entry["file_sha256"],
                                  entry["pages"], request["request_sha256"], path))
    if len({m.sha256 for m in materials}) != 11:
        raise RuntimeError("new sources are not unique")
    if len({(m.filename, m.size) for m in materials}) != 11 or len({m.md5 for m in materials}) != 11:
        raise RuntimeError("new upload identities are not unique")
    old = {}
    old_materials = {}
    for mid in OLD_KNOWLEDGE_IDS:
        value = load_json(evidence / "inputs/existing-revisions" / f"{mid}.json")
        old[mid] = value["descriptor"]
        if old[mid]["knowledge_id"] != OLD_KNOWLEDGE_IDS[mid]:
            raise RuntimeError("old descriptor identity drift")
        entry = entry_by_id[mid]
        relative = Path(entry["path"])
        path = (root / relative).resolve()
        raw = regular_file(path)
        if len(raw) != entry["size_bytes"] or sha256_bytes(raw) != entry["file_sha256"]:
            raise RuntimeError(f"old source bytes drift: {mid}")
        old_materials[mid] = Material(mid, path.name, len(raw), file_md5(path),
                                      entry["file_sha256"], entry["pages"], path=path)
    old_by_knowledge = {row["knowledge_id"]: row["revision_source_id"]
                        for row in runtime_preflight["database"]["source_rows"]}
    actual_old_ids = {mid: old_by_knowledge[kid] for mid, kid in OLD_KNOWLEDGE_IDS.items()
                      if kid in old_by_knowledge}
    validate_old_source_ids(actual_old_ids)
    return FrozenInputs(tuple(materials), old_materials, copy.deepcopy(offline["process_config"]),
                        MANIFEST_SHA256, old)


def validate_initial_scope(existing: list[dict[str, Any]], materials: list[Material] | tuple[Material, ...],
                           old: dict[str, Material]) -> None:
    for material in materials:
        conflicts = [row for row in existing if (
            row.get("file_hash") == material.md5
            or row.get("file_sha256") == material.sha256
            or (row.get("file_name") == material.filename and row.get("file_size") == material.size)
        )]
        if conflicts:
            raise RuntimeError(f"pre-upload conflict: {material.material_id}")
    if len(existing) != 4 or set(old) != set(OLD_KNOWLEDGE_IDS):
        raise RuntimeError("target scope does not contain exact cloned four")
    if {row.get("id") for row in existing} != set(OLD_KNOWLEDGE_IDS.values()):
        raise RuntimeError("target scope does not contain exact cloned four")
    for row in existing:
        if row.get("tenant_id") != TENANT_ID or row.get("knowledge_base_id") != RAW_KB_ID:
            raise RuntimeError("target scope drift")
        mid = next(key for key, value in OLD_KNOWLEDGE_IDS.items() if value == row["id"])
        material = old[mid]
        if (row.get("file_name") != material.filename or row.get("file_size") != material.size
                or row.get("file_hash") != material.md5 or row.get("file_sha256") != material.sha256):
            raise RuntimeError(f"cloned source identity drift: {mid}")


def validate_kb(kb: dict[str, Any]) -> None:
    if kb.get("id") != RAW_KB_ID or kb.get("tenant_id") != TENANT_ID:
        raise RuntimeError("KB identity drift")
    if kb.get("summary_model_id") not in (None, "") or kb.get("token_limit", 0) != 0:
        raise RuntimeError("KB derived task config is unsafe")
    if kb.get("languages", []) != [] or kb.get("wiki_config") not in (None, {}, {"enabled": False}):
        raise RuntimeError("KB wiki/language config is unsafe")
    indexing = kb.get("indexing_strategy") or {}
    if indexing.get("graph_enabled", False) or indexing.get("wiki_enabled", False):
        raise RuntimeError("KB graph/wiki config is unsafe")
    qgen = kb.get("question_generation_config") or {}
    if qgen.get("enabled", False):
        raise RuntimeError("KB qgen is unsafe")


def validate_runtime_precondition(provision: dict[str, Any], app_inspect: dict[str, Any],
                                  doc_inspect: dict[str, Any], redis_inspect: dict[str, Any],
                                  kb: dict[str, Any], model: dict[str, Any],
                                  pg_inspect: dict[str, Any] | None = None) -> None:
    if (provision.get("contract") != "830-g3-source-runtime-provision-apply.v1"
            or provision.get("status") != "PASS" or provision.get("script_sha256") != PROVISION_SHA256):
        raise RuntimeError("provision receipt is not PASS")
    expected = ((APP, APP_IMAGE, app_inspect), (DOCREADER, DOCREADER_IMAGE, doc_inspect),
                (REDIS, REDIS_IMAGE, redis_inspect))
    for name, image, inspect in expected:
        if inspect.get("Name", "").lstrip("/") != name or inspect.get("Image") != image:
            raise RuntimeError(f"runtime identity drift: {name}")
        if not inspect.get("State", {}).get("Running"):
            raise RuntimeError(f"runtime not running: {name}")
        networks = set((inspect.get("NetworkSettings", {}).get("Networks") or {}).keys())
        if networks != {INTERNAL_NETWORK}:
            raise RuntimeError(f"runtime network drift: {name}")
    app_env = parse_env(app_inspect.get("Config", {}).get("Env", []))
    redis_env = parse_env(redis_inspect.get("Config", {}).get("Env", []))
    if (app_env.get("BATCH_EMBED_SIZE") != "100" or app_env.get("REDIS_DB") != "0"
            or app_env.get("DB_HOST") != "postgres-g3" or app_env.get("DB_PORT") != "5432"
            or app_env.get("DB_NAME") != TARGET_DB or app_env.get("DB_USER") != DB_USER
            or app_env.get("REDIS_ADDR") != "redis-g3:6379"):
        raise RuntimeError("app batch/redis config drift")
    if redis_env.get("REDIS_PASSWORD") in (None, ""):
        raise RuntimeError("independent redis lacks password")
    if pg_inspect is not None:
        pg_network = (pg_inspect.get("NetworkSettings", {}).get("Networks") or {}).get(INTERNAL_NETWORK) or {}
        if (pg_inspect.get("Name", "").lstrip("/") != PG_CONTAINER or pg_inspect.get("Image") != PG_IMAGE
                or not pg_inspect.get("State", {}).get("Running")
                or "postgres-g3" not in (pg_network.get("Aliases") or [])):
            raise RuntimeError("target PostgreSQL binding drift")
    validate_kb(kb)
    parameters = model.get("parameters") or {}
    if (model.get("id") != MODEL_ID or model.get("tenant_id") != TENANT_ID
            or model.get("is_builtin") is not False or parameters.get("base_url") != GUARD_BASE_URL):
        raise RuntimeError("embedding model guard binding drift")


def parse_env(rows: list[str]) -> dict[str, str]:
    result = {}
    for row in rows:
        if "\x00" in row or "\r" in row or "\n" in row or "=" not in row:
            raise RuntimeError("unsafe runtime env")
        key, value = row.split("=", 1)
        if key in result:
            raise RuntimeError("duplicate runtime env")
        result[key] = value
    return result


class RunState:
    def __init__(self, path: Path, initial: dict[str, Any]):
        self.path = path
        self.value = initial
        atomic_json(path, initial, exclusive=True)

    def save(self) -> None:
        atomic_json(self.path, self.value)

    def checkpoint(self, step: str, details: dict[str, Any] | None = None) -> None:
        self.value["last_step"] = step
        self.value.setdefault("steps", []).append({"step": step, "details": details or {}})
        self.save()

    def begin_post(self, label: str) -> None:
        self.value["current_post"] = {"label": label, "status": "STARTED"}
        self.checkpoint(f"{label}-started")

    def record_http(self, label: str, status: int, digest: str, artifact: str | None) -> None:
        self.value.setdefault("http_responses", []).append({
            "label": label, "http_status": status, "response_sha256": digest,
            "artifact": artifact,
        })
        self.save()

    def finish_post(self, label: str, status: str, details: dict[str, Any]) -> None:
        self.value["current_post"] = {"label": label, "status": status, **details}
        self.checkpoint(f"{label}-{status.lower()}")

    def begin_material(self, material: Material) -> None:
        row = self.value["materials"][material.material_id]
        if row["status"] != "NOT_STARTED":
            raise RuntimeError("material cannot resume")
        row["status"] = "STARTED"
        self.save()

    def fail_material(self, material: Material, status: str, error_type: str) -> None:
        self.value["materials"][material.material_id].update(status=status, error_type=error_type)
        self.value["status"] = status
        self.save()

    def complete_material(self, material: Material, result: dict[str, Any]) -> None:
        self.value["materials"][material.material_id].update(status="PASS", result=result)
        self.save()


def single_post(state: Any, send: Callable[[], Any], label: str) -> Any:
    state.begin_post(label)
    return send()


def execute_material_sequence(materials: list[Material] | tuple[Material, ...], state: Any,
                              worker: Callable[[Material], dict[str, Any]]) -> None:
    for material in materials:
        state.begin_material(material)
        try:
            result = worker(material)
        except TimeoutError:
            state.fail_material(material, "RESULT_UNKNOWN", "TimeoutError")
            raise
        except Exception as error:
            state.fail_material(material, "STOPPED", type(error).__name__)
            raise
        state.complete_material(material, result)


def validate_guard_ledger(ledger: dict[str, Any], completed: list[Material]) -> None:
    attempts = ledger.get("attempts")
    if ledger.get("manifest_sha256") not in (None, MANIFEST_SHA256) or not isinstance(attempts, list):
        raise RuntimeError("guard ledger shape drift")
    if len(attempts) != len(completed):
        raise RuntimeError("guard attempt count drift")
    for index, (row, material) in enumerate(zip(attempts, completed), 1):
        expected = {"attempt": index, "material_id": material.material_id,
                    "source_sha256": material.sha256, "request_sha256": material.request_sha256,
                    "status": "RESPONSE", "http_status": 200}
        if any(row.get(key) != value for key, value in expected.items()):
            raise RuntimeError(f"provider attempt failed: {material.material_id}")
    if ledger.get("stopped"):
        raise RuntimeError("provider attempt failed: guard stopped")


def separator_digest(separators: list[str]) -> str:
    raw = "weknora.chunk_separators\nv1\n" + str(len(separators)) + "\n"
    for value in separators:
        raw += f"{len(value.encode())}:{value}\n"
    return sha256_bytes(raw.encode())


def expected_parser_identity_projection() -> dict[str, Any]:
    cfg = expected_process_config()["chunking_config"]
    sep = separator_digest(cfg["separators"])
    chunker = sha256_bytes(
        f"weknora.chunker_config\nv1\n{cfg['chunk_size']}\n{cfg['chunk_overlap']}\n{sep}\nbuiltin\n".encode()
    )
    return {"app_version": "unknown", "app_commit": "unknown", "docreader": "unknown",
            "parser_engine": "builtin", "chunk_size": 2048, "chunk_overlap": 80,
            "separators_digest": sep, "chunker_config_digest": chunker,
            "embedding_model_id": MODEL_ID}


def compute_manifest_digest(knowledge_id: str, attempt: int, chunks: list[dict[str, Any]]) -> str:
    if not knowledge_id or attempt <= 0:
        raise RuntimeError("invalid revision identity")
    ordered = sorted(chunks, key=lambda row: row["chunk_index"])
    if ordered != chunks or [row["chunk_index"] for row in ordered] != sorted({row["chunk_index"] for row in ordered}):
        raise RuntimeError("chunks not strictly ordered")
    raw = f"weknora.chunk_manifest\nv1\n{knowledge_id}\n{attempt}\n{len(chunks)}\n"
    previous = -1
    for row in chunks:
        index, chunk_id, content = row.get("chunk_index"), row.get("id"), row.get("content")
        if not isinstance(index, int) or index <= previous or not chunk_id or not isinstance(content, str):
            raise RuntimeError("invalid revision chunk")
        previous = index
        raw += f"{index}:{chunk_id}:{sha256_bytes(content.encode())}\n"
    return sha256_bytes(raw.encode())


def _validate_descriptor(descriptor: dict[str, Any], chunks: list[dict[str, Any]], file_sha256: str) -> None:
    kid, attempt = descriptor.get("knowledge_id"), descriptor.get("parse_attempt")
    manifest = descriptor.get("chunk_manifest") or {}
    if descriptor.get("file_digest") != {"algorithm": "sha256", "value": file_sha256}:
        raise RuntimeError("revision file digest mismatch")
    if (manifest.get("algorithm") != "weknora.chunk_manifest.v1"
            or manifest.get("chunk_count") != len(chunks)
            or manifest.get("digest") != compute_manifest_digest(kid, attempt, chunks)):
        raise RuntimeError("revision manifest mismatch")


def validate_revision_capture(before: dict[str, Any], after: dict[str, Any], chunks: list[dict[str, Any]],
                              process_config: dict[str, Any], file_sha256: str) -> None:
    if canonical(before) != canonical(after):
        raise RuntimeError("descriptor drift")
    if process_config != expected_process_config():
        raise RuntimeError("process config drift")
    _validate_descriptor(before, chunks, file_sha256)
    actual = before.get("parser_identity") or {}
    expected = expected_parser_identity_projection()
    for key, value in expected.items():
        if key in ("app_version", "app_commit", "docreader"):
            if not isinstance(actual.get(key), str) or not actual[key].strip():
                raise RuntimeError("parser build identity missing")
        elif actual.get(key) != value:
            raise RuntimeError(f"parser identity drift: {key}")


def validate_existing_revision_capture(before: dict[str, Any], after: dict[str, Any],
                                       chunks: list[dict[str, Any]], frozen: dict[str, Any]) -> None:
    if canonical(before) != canonical(after) or canonical(before) != canonical(frozen):
        raise RuntimeError("existing descriptor drift")
    _validate_descriptor(before, chunks, frozen["file_digest"]["value"])


def validate_source_receipt(receipt: dict[str, Any], material: Material,
                            descriptor: dict[str, Any], knowledge_id: str) -> None:
    manifest = descriptor["chunk_manifest"]
    expected = {
        "contract": "knowledge-revision-source.v1", "knowledge_id": knowledge_id,
        "parse_attempt": descriptor["parse_attempt"], "file_sha256": material.sha256,
        "object_sha256": material.sha256, "size": material.size,
        "mime_type": "application/pdf", "page_count": material.pages,
        "manifest_algorithm": "weknora.chunk_manifest.v1",
        "manifest_digest": manifest["digest"], "chunk_count": manifest["chunk_count"],
        "retention_state": "pinned",
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise RuntimeError("source receipt binding mismatch")
    for key in ("revision_source_id", "binding_digest"):
        value = receipt.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise RuntimeError(f"source receipt {key} invalid")


def validate_old_source_ids(values: dict[str, str]) -> None:
    if values != OLD_SOURCE_IDS:
        raise RuntimeError("old source identity drift")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_: Any, **__: Any) -> None:
        return None


class ResultUnknownError(TimeoutError):
    """A mutating request may have reached the server; automatic retry is forbidden."""


class LoopbackAPI:
    def __init__(self, origin: str = API_ORIGIN):
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port != 18294:
            raise RuntimeError("API must be exact loopback endpoint")
        self.origin = origin.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.token: str | None = None

    def request(self, method: str, path: str, *, body: bytes | None = None,
                headers: dict[str, str] | None = None, timeout: float = 60) -> tuple[int, bytes]:
        if not path.startswith("/api/v1/") or urllib.parse.urlsplit(path).netloc:
            raise RuntimeError("unsafe API path")
        values = dict(headers or {})
        if self.token:
            values["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.origin + path, data=body, headers=values, method=method)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()


class UploadExecutor:
    def __init__(self, api: LoopbackAPI, state: RunState, artifacts: Path,
                 frozen: FrozenInputs, guard_ledger_reader: Callable[[], dict[str, Any]],
                 sleep: Callable[[float], None] = time.sleep):
        self.api, self.state, self.artifacts, self.frozen = api, state, artifacts, frozen
        self.guard_ledger_reader, self.sleep = guard_ledger_reader, sleep
        self.completed: list[Material] = []

    def _save_response(self, label: str, status: int, raw: bytes) -> str:
        safe = label.replace(":", "-").replace("/", "-")
        path = self.artifacts / f"{safe}.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            remaining = raw
            while remaining:
                remaining = remaining[os.write(fd, remaining):]
            os.fsync(fd)
        finally:
            os.close(fd)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        return sha256_bytes(raw)

    def request_json(self, method: str, path: str, label: str, *, body: bytes | None = None,
                     headers: dict[str, str] | None = None, post: bool = False,
                     timeout: float = 60, persist_raw: bool = True) -> dict[str, Any]:
        if post:
            self.state.begin_post(label)
        try:
            status, raw = self.api.request(method, path, body=body, headers=headers, timeout=timeout)
        except TimeoutError:
            if post:
                self.state.finish_post(label, "RESULT_UNKNOWN", {"error_type": "TimeoutError"})
            raise
        except Exception as error:
            if post:
                self.state.finish_post(label, "RESULT_UNKNOWN", {"error_type": type(error).__name__})
                raise ResultUnknownError("single-send transport result unknown") from error
            raise
        digest = self._save_response(label, status, raw) if persist_raw else sha256_bytes(raw)
        artifact = label.replace(":", "-").replace("/", "-") + ".json" if persist_raw else None
        self.state.record_http(label, status, digest, artifact)
        if post:
            self.state.finish_post(label, "RESPONSE", {"http_status": status, "response_sha256": digest})
        if status != 200:
            raise RuntimeError(f"{label} returned HTTP {status}")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise RuntimeError(f"{label} response is not object")
        return value

    def list_all(self) -> list[dict[str, Any]]:
        rows, page = [], 1
        while page <= 100:
            value = self.request_json("GET", f"/api/v1/knowledge-bases/{RAW_KB_ID}/knowledge?page={page}&page_size=100",
                                      f"preflight-list-{page}")
            data = value.get("data")
            if not isinstance(data, list):
                raise RuntimeError("knowledge list shape drift")
            rows.extend(data)
            total = value.get("total")
            if not isinstance(total, int) or len(rows) > total:
                raise RuntimeError("knowledge list total drift")
            if len(rows) == total:
                return rows
            if not data:
                raise RuntimeError("knowledge pagination made no progress")
            page += 1
        raise RuntimeError("knowledge pagination exceeded bound")

    def upload_body(self, material: Material) -> tuple[bytes, str]:
        assert material.path is not None
        boundary = "g3-830-" + secrets.token_hex(16)
        file_raw = regular_file(material.path, material.sha256)
        if len(file_raw) != material.size or file_md5(material.path) != material.md5:
            raise RuntimeError("source changed immediately before upload")
        fields = (("fileName", material.filename.encode()),
                  ("process_config", canonical(self.frozen.process_config)))
        chunks: list[bytes] = []
        for name, value in fields:
            chunks += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode(),
                       value, b"\r\n"]
        chunks += [f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{material.filename}\"\r\n".encode(),
                   b"Content-Type: application/pdf\r\n\r\n", file_raw, b"\r\n",
                   f"--{boundary}--\r\n".encode()]
        return b"".join(chunks), boundary

    def upload(self, material: Material) -> dict[str, Any]:
        body, boundary = self.upload_body(material)
        value = self.request_json("POST", f"/api/v1/knowledge-bases/{RAW_KB_ID}/knowledge/file",
                                  f"upload:{material.material_id}", body=body,
                                  headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                                  post=True, timeout=180)
        row = value.get("data")
        if not isinstance(row, dict):
            raise RuntimeError("upload response lacks knowledge")
        if (row.get("tenant_id") != TENANT_ID or row.get("knowledge_base_id") != RAW_KB_ID
                or row.get("file_name") != material.filename or row.get("file_size") != material.size
                or row.get("file_hash") != material.md5 or row.get("file_sha256") != material.sha256
                or not isinstance(row.get("id"), str) or not row["id"]):
            raise RuntimeError("upload response binding drift")
        metadata = row.get("metadata") or {}
        if metadata.get("process_overrides") != expected_persisted_process_overrides():
            raise RuntimeError("upload process_overrides drift")
        return row

    def wait_completed(self, knowledge_id: str, material_id: str,
                       max_polls: int = 180, interval: float = 2.0) -> dict[str, Any]:
        for poll in range(max_polls):
            value = self.request_json("GET", f"/api/v1/knowledge/{knowledge_id}",
                                      f"wait-{material_id}-{poll}")
            row = value.get("data") or {}
            status = row.get("parse_status")
            if status == "completed":
                return row
            if status in ("failed", "cancelled"):
                raise RuntimeError(f"knowledge parse terminal: {status}")
            self.sleep(interval)
        raise TimeoutError("knowledge completion deadline exceeded")

    def revision(self, knowledge_id: str, label: str) -> dict[str, Any]:
        value = self.request_json("GET", f"/api/v1/knowledge/{knowledge_id}/revision", label)
        descriptor = value.get("data")
        if not isinstance(descriptor, dict):
            raise RuntimeError("revision descriptor missing")
        return descriptor

    def chunks(self, knowledge_id: str, attempt: int, label: str) -> list[dict[str, Any]]:
        rows, page = [], 1
        while page <= 100:
            value = self.request_json("GET", f"/api/v1/knowledge/{knowledge_id}/revisions/{attempt}/chunks?page={page}&page_size=100",
                                      f"{label}-{page}")
            data = value.get("data")
            if not isinstance(data, list):
                raise RuntimeError("revision chunks missing")
            rows.extend(data)
            total = value.get("total")
            if not isinstance(total, int) or len(rows) > total:
                raise RuntimeError("revision chunk total drift")
            if len(rows) == total:
                return rows
            if not data:
                raise RuntimeError("chunk pagination made no progress")
            page += 1
        raise RuntimeError("chunk pagination exceeded bound")

    def capture_new(self, material: Material, knowledge_id: str) -> dict[str, Any]:
        before = self.revision(knowledge_id, f"revision-before-{material.material_id}")
        chunks = self.chunks(knowledge_id, before["parse_attempt"], f"chunks-{material.material_id}")
        after = self.revision(knowledge_id, f"revision-after-{material.material_id}")
        validate_revision_capture(before, after, chunks, self.frozen.process_config, material.sha256)
        return before

    def capture_old(self, material_id: str) -> dict[str, Any]:
        knowledge_id = OLD_KNOWLEDGE_IDS[material_id]
        frozen = self.frozen.old_descriptors[material_id]
        before = self.revision(knowledge_id, f"old-revision-before-{material_id}")
        chunks = self.chunks(knowledge_id, before["parse_attempt"], f"old-chunks-{material_id}")
        after = self.revision(knowledge_id, f"old-revision-after-{material_id}")
        validate_existing_revision_capture(before, after, chunks, frozen)
        return before

    def backfill(self, material: Material, descriptor: dict[str, Any], knowledge_id: str) -> dict[str, Any]:
        attempt = descriptor["parse_attempt"]
        value = self.request_json("POST", f"/api/v1/knowledge/{knowledge_id}/revisions/{attempt}/source/backfill",
                                  f"backfill:{material.material_id}", post=True)
        receipt = value.get("data")
        if not isinstance(receipt, dict):
            raise RuntimeError("source receipt missing")
        validate_source_receipt(receipt, material, descriptor, knowledge_id)
        return receipt

    def run_new(self, material: Material) -> dict[str, Any]:
        row = self.upload(material)
        self.wait_completed(row["id"], material.material_id)
        ledger = self.guard_ledger_reader()
        validate_guard_ledger(ledger, self.completed + [material])
        descriptor = self.capture_new(material, row["id"])
        receipt = self.backfill(material, descriptor, row["id"])
        self.completed.append(material)
        return {"knowledge_id": row["id"], "parse_attempt": descriptor["parse_attempt"],
                "manifest_digest": descriptor["chunk_manifest"]["digest"],
                "revision_source_id": receipt["revision_source_id"]}


def authenticate(api: LoopbackAPI, state: RunState, email: str, password: str) -> dict[str, Any]:
    body = canonical({"email": email, "password": password})
    state.begin_post("human-login")
    try:
        status, raw = api.request("POST", "/api/v1/auth/login", body=body,
                                  headers={"Content-Type": "application/json"}, timeout=30)
    except TimeoutError:
        state.finish_post("human-login", "RESULT_UNKNOWN", {"error_type": "TimeoutError"})
        raise
    if status != 200:
        state.finish_post("human-login", "RESPONSE", {"http_status": status})
        raise RuntimeError("human login failed")
    value = json.loads(raw)
    token = value.get("token")
    user = value.get("user") or {}
    active = value.get("active_tenant") or {}
    memberships = value.get("memberships") or []
    membership = [row for row in memberships if row.get("tenant_id") == TENANT_ID]
    if (value.get("success") is not True or not isinstance(token, str) or not token
            or active.get("id") != TENANT_ID
            or len(membership) != 1 or membership[0].get("role") != "admin"
            or user.get("tenant_id") != TENANT_ID):
        raise RuntimeError("login identity is not tenant10003 human Admin")
    api.token = token
    me_status, me_raw = api.request("GET", "/api/v1/auth/me", timeout=30)
    if me_status != 200:
        raise RuntimeError("authenticated identity readback failed")
    me = json.loads(me_raw).get("data") or {}
    me_user, me_tenant, me_memberships = me.get("user") or {}, me.get("tenant") or {}, me.get("memberships") or []
    me_membership = [row for row in me_memberships if row.get("tenant_id") == TENANT_ID]
    if (me_user.get("id") != user.get("id") or me_tenant.get("id") != TENANT_ID
            or len(me_membership) != 1
            or me_membership[0].get("role") != "admin"):
        raise RuntimeError("authenticated identity readback drift")
    state.finish_post("human-login", "PASS", {"http_status": 200,
        "login_response_sha256": sha256_bytes(raw), "tenant_id": TENANT_ID,
        "user_id": user.get("id"), "role": "admin", "me_sha256": sha256_bytes(me_raw)})
    return user


def validate_authorization(path: Path, runner_sha: str, provision_sha: str) -> dict[str, Any]:
    value = json.loads(regular_file(path))
    expected = {"contract": "830-g3-source-upload-authorization.v1", "decision": "APPROVED",
                "tenant_id": TENANT_ID, "raw_kb_id": RAW_KB_ID,
                "manifest_sha256": MANIFEST_SHA256, "runner_sha256": runner_sha,
                "provision_receipt_sha256": provision_sha,
                "authorized_material_ids": list(MATERIAL_IDS),
                "authorized_actions": ["upload", "embedding-external-send", "source-backfill"]}
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise RuntimeError("external-send authorization mismatch")
    if not value.get("approved_at"):
        raise RuntimeError("external-send authorization lacks approved_at")
    return value


class DockerRuntime:
    """Minimal docker adapter. Calls are only reachable from explicit ``run`` mode."""
    def __init__(self, command: list[str]):
        self.command = command
        self.guard_started = False
        self.egress_created = False
        self.egress_connected = False

    def call(self, args: list[str], *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(self.command + args, input=input_bytes, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=check, timeout=120)

    def inspect(self, name: str) -> dict[str, Any]:
        result = self.call(["inspect", name])
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError("docker inspect cardinality drift")
        return rows[0]

    def copy_regular(self, local: Path, remote_name: str) -> None:
        raw = regular_file(local)
        script = ("import os,sys; p=sys.argv[1]; fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600); "
                  "f=os.fdopen(fd,'wb'); d=sys.stdin.buffer.read(); assert f.write(d)==len(d); "
                  "f.flush(); os.fsync(f.fileno()); f.close(); q=os.open(os.path.dirname(p),os.O_RDONLY); os.fsync(q); os.close(q)")
        self.call(["exec", "-i", APP, "python3", "-c", script, remote_name], input_bytes=raw)

    def prepare_stage(self, frozen: FrozenInputs) -> str:
        staged = "/run/g3-830-upload"
        self.call(["exec", APP, "mkdir", "-m", "0700", staged])
        self.call(["exec", APP, "mkdir", "-m", "0700", f"{staged}/root"])
        self.call(["exec", APP, "mkdir", "-m", "0700", f"{staged}/root/docs"])
        self.call(["exec", APP, "mkdir", "-m", "0700", f"{staged}/root/docs/insurance-kb"])
        self.call(["exec", APP, "mkdir", "-m", "0700", f"{staged}/root/docs/insurance-kb/evidence"])
        self.call(["exec", APP, "mkdir", "-m", "0700", f"{staged}/root/docs/insurance-kb/evidence/830-g3"])
        self.call(["exec", APP, "mkdir", "-m", "0700", f"{staged}/root/docs/insurance-kb/evidence/830-g3/inputs"])
        request_dir = f"{staged}/root/docs/insurance-kb/evidence/830-g3/inputs/embedding-requests"
        self.call(["exec", APP, "mkdir", "-m", "0700", request_dir])
        self.copy_regular(EVIDENCE / "embedding_guard.py", f"{staged}/embedding_guard.py")
        self.copy_regular(EVIDENCE / "embedding-transport-manifest.json",
                          f"{staged}/embedding-transport-manifest.json")
        for material in frozen.materials:
            source = EVIDENCE / "inputs/embedding-requests" / f"{material.material_id}-request.json"
            self.copy_regular(source, f"{request_dir}/{source.name}")
        expected = {f"{staged}/embedding_guard.py": GUARD_SHA256,
                    f"{staged}/embedding-transport-manifest.json": MANIFEST_SHA256}
        expected.update({f"{request_dir}/{m.material_id}-request.json": m.request_sha256
                         for m in frozen.materials})
        verifier = ("import hashlib,json,os,stat,sys; expected=json.loads(sys.argv[1]); "
                    "actual={}; "
                    "[(lambda p,s: (None if stat.S_ISREG(s.st_mode) and s.st_nlink==1 else "
                    "(_ for _ in ()).throw(RuntimeError('not regular')), actual.__setitem__(p,hashlib.sha256(open(p,'rb').read()).hexdigest())))(p,os.lstat(p)) for p in expected]; "
                    "assert actual==expected; print(json.dumps(actual,sort_keys=True))")
        result = self.call(["exec", APP, "python3", "-c", verifier,
                            json.dumps(expected, sort_keys=True, separators=(",", ":"))])
        if json.loads(result.stdout) != expected:
            raise RuntimeError("staged guard files drift")
        return staged

    def start_guard(self, staged: str) -> None:
        self.call(["exec", APP, "sh", "-c",
                   f"umask 077; nohup python3 {staged}/embedding_guard.py "
                   f"{staged}/root {staged}/embedding-transport-manifest.json {MANIFEST_SHA256} "
                   f"{staged}/ledger.json </dev/null >{staged}/guard.out 2>{staged}/guard.err & echo $! >{staged}/guard.pid"])
        self.guard_started = True
        probe_script = """import json, socket, time
deadline = time.monotonic() + 5
while True:
    try:
        s = socket.create_connection(('127.0.0.1', 19030), .5)
        s.close()
        break
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(.1)
d = json.load(open('/run/g3-830-upload/ledger.json'))
assert d['attempts'] == [] and not d['stopped'] and d['manifest_sha256'] == %r
""" % MANIFEST_SHA256
        probe = self.call(["exec", APP, "python3", "-c", probe_script])
        if probe.returncode != 0:
            raise RuntimeError("guard did not start empty on loopback")

    def read_guard_ledger(self) -> dict[str, Any]:
        result = self.call(["exec", APP, "cat", "/run/g3-830-upload/ledger.json"])
        value = json.loads(result.stdout)
        if not isinstance(value, dict):
            raise RuntimeError("guard ledger is not object")
        return value

    def copy_guard_ledger(self, local: Path) -> None:
        result = self.call(["exec", APP, "cat", "/run/g3-830-upload/ledger.json"])
        fd = os.open(local, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            remaining = result.stdout
            while remaining:
                remaining = remaining[os.write(fd, remaining):]
            os.fsync(fd)
        finally:
            os.close(fd)

    def create_egress(self) -> None:
        self.call(["network", "create", "--driver", "bridge", EGRESS_NETWORK])
        self.egress_created = True
        self.call(["network", "connect", EGRESS_NETWORK, APP])
        self.egress_connected = True
        result = self.call(["network", "inspect", EGRESS_NETWORK])
        rows = json.loads(result.stdout)
        containers = list((rows[0].get("Containers") or {}).values()) if len(rows) == 1 else []
        if rows[0].get("Driver") != "bridge" or [row.get("Name") for row in containers] != [APP]:
            raise RuntimeError("egress network membership drift")

    def stop_guard(self) -> bool:
        if not self.guard_started:
            return True
        result = self.call(["exec", APP, "sh", "-c", "p=$(cat /run/g3-830-upload/guard.pid); kill -TERM $p; "
                            "i=0; while kill -0 $p 2>/dev/null && test $i -lt 50; do i=$((i+1)); sleep .1; done; "
                            "! kill -0 $p 2>/dev/null"], check=False)
        stopped = result.returncode == 0
        if stopped:
            self.guard_started = False
        return stopped

    def disconnect_egress(self) -> bool:
        if not self.egress_created:
            return True
        if self.egress_connected:
            result = self.call(["network", "disconnect", EGRESS_NETWORK, APP], check=False)
            if result.returncode != 0:
                return False
        result = self.call(["network", "rm", EGRESS_NETWORK], check=False)
        removed = result.returncode == 0
        if removed:
            self.egress_created = False
            self.egress_connected = False
        return removed

    def stop_failed_runtime(self) -> dict[str, bool]:
        result = {}
        for name in (APP, DOCREADER):
            try:
                result[name] = self.call(["stop", "--time", "30", name], check=False).returncode == 0
            except Exception:
                result[name] = False
        for name in (APP, DOCREADER):
            try:
                inspected = self.inspect(name)
                result[name] = result[name] and not inspected.get("State", {}).get("Running", True)
            except Exception:
                result[name] = False
        return result

    def verify_target_python(self) -> dict[str, Any]:
        script = ("import json,os,ssl,sys,urllib.request,http.server; "
                  "print(json.dumps({'major':sys.version_info[0],'ca':os.path.isfile(ssl.get_default_verify_paths().cafile or '')},sort_keys=True))")
        result = self.call(["exec", APP, "python3", "-c", script])
        value = json.loads(result.stdout)
        if value != {"major": 3, "ca": True}:
            raise RuntimeError("target Python stdlib/CA preflight failed")
        return value

    def assert_egress_absent(self) -> None:
        result = self.call(["network", "ls", "--filter", f"name=^{EGRESS_NETWORK}$",
                            "--format", "{{.Name}}"])
        names = [line.strip() for line in result.stdout.decode().splitlines() if line.strip()]
        if names:
            raise RuntimeError("dedicated egress network already exists")


def teardown(runtime: Any, failed: bool) -> dict[str, Any]:
    try:
        guard = bool(runtime.stop_guard())
    except Exception:
        guard = False
    try:
        egress = bool(runtime.disconnect_egress())
    except Exception:
        egress = False
    try:
        processes = runtime.stop_failed_runtime() if failed else {}
    except Exception:
        processes = {APP: False, DOCREADER: False} if failed else {}
    complete = guard and egress and (not failed or all(processes.get(name) for name in (APP, DOCREADER)))
    return {"status": "STOPPED" if complete else "STOP_INCOMPLETE",
            "guard_stopped": guard, "egress_removed": egress, "processes": processes}


def initial_receipt(runner_sha: str, provision_sha: str, authorization_sha: str,
                    materials: tuple[Material, ...]) -> dict[str, Any]:
    return {"contract": "830-g3-source-upload-run.v1", "status": "STARTED",
            "runner_sha256": runner_sha, "provision_receipt_sha256": provision_sha,
            "authorization_sha256": authorization_sha, "manifest_sha256": MANIFEST_SHA256,
            "tenant_id": TENANT_ID, "raw_kb_id": RAW_KB_ID,
            "materials": {m.material_id: {"status": "NOT_STARTED", "source_sha256": m.sha256,
                                           "request_sha256": m.request_sha256} for m in materials},
            "steps": [], "last_step": None}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", choices=["run"])
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--provision-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--email-file", type=Path, required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--docker-command-json", required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    runner_sha = file_sha256(Path(__file__))
    frozen = load_frozen_inputs(WORKTREE)
    provision_raw = regular_file(args.provision_receipt)
    provision_sha = sha256_bytes(provision_raw)
    provision = json.loads(provision_raw)
    auth_sha_before = file_sha256(args.authorization)
    validate_authorization(args.authorization, runner_sha, provision_sha)
    if file_sha256(args.authorization) != auth_sha_before:
        raise RuntimeError("authorization changed while validating")
    if provision.get("contract") != "830-g3-source-runtime-provision-apply.v1" or provision.get("status") != "PASS":
        raise RuntimeError("provision receipt is not PASS")
    args.artifact_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    state = RunState(args.receipt, initial_receipt(runner_sha, provision_sha,
                     auth_sha_before, frozen.materials))
    runtime = DockerRuntime(json.loads(args.docker_command_json))
    failed = True
    try:
        api = LoopbackAPI()
        email = secret_line(args.email_file, trim_outer_space=True)
        password = secret_line(args.password_file, trim_outer_space=False)
        if not email or not password:
            raise RuntimeError("empty human credential")
        authenticate(api, state, email, password)
        # Runtime/KB/model checks and the exact-four list occur before the first
        # mutating upload/backfill POST. Login itself is an authentication POST.
        app_i, doc_i, redis_i = runtime.inspect(APP), runtime.inspect(DOCREADER), runtime.inspect(REDIS)
        pg_i = runtime.inspect(PG_CONTAINER)
        python_probe = runtime.verify_target_python()
        runtime.assert_egress_absent()
        dummy = UploadExecutor(api, state, args.artifact_dir, frozen,
                               lambda: load_json(args.artifact_dir / "guard-ledger.json"))
        kb = dummy.request_json("GET", f"/api/v1/knowledge-bases/{RAW_KB_ID}", "preflight-kb").get("data") or {}
        model = dummy.request_json("GET", f"/api/v1/models/{MODEL_ID}", "preflight-model",
                                   persist_raw=False).get("data") or {}
        validate_runtime_precondition(provision, app_i, doc_i, redis_i, kb, model, pg_i)
        existing = dummy.list_all()
        validate_initial_scope(existing, frozen.materials, frozen.old_materials)
        state.checkpoint("readonly-preflight-pass", {"existing_count": 4, "new_count": 11,
                                                      "target_python": python_probe})
        state.checkpoint("guard-staging-started")
        staged = runtime.prepare_stage(frozen)
        state.checkpoint("guard-staging-pass", {"path": staged})
        state.checkpoint("guard-start-started")
        runtime.start_guard(staged)
        state.checkpoint("guard-start-pass", {"attempt_count": 0})
        state.checkpoint("egress-create-started", {"network": EGRESS_NETWORK, "scope": APP})
        runtime.create_egress()
        state.checkpoint("egress-create-pass", {"network": EGRESS_NETWORK, "scope": APP})
        executor = UploadExecutor(api, state, args.artifact_dir, frozen, runtime.read_guard_ledger)
        execute_material_sequence(frozen.materials, state, executor.run_new)
        ledger = runtime.read_guard_ledger()
        validate_guard_ledger(ledger, list(frozen.materials))
        runtime.copy_guard_ledger(args.artifact_dir / "guard-ledger-final.json")
        state.checkpoint("guard-ledger-preserved", {
            "artifact": "guard-ledger-final.json",
            "sha256": file_sha256(args.artifact_dir / "guard-ledger-final.json")})
        external_close = teardown(runtime, failed=False)
        state.checkpoint("external-window-closed", external_close)
        if external_close["status"] != "STOPPED":
            raise RuntimeError("external window teardown incomplete")
        old_source_ids = {}
        for mid in sorted(OLD_KNOWLEDGE_IDS):
            material = frozen.old_materials[mid]
            descriptor = executor.capture_old(mid)
            receipt = executor.backfill(material, descriptor, OLD_KNOWLEDGE_IDS[mid])
            if mid in OLD_SOURCE_IDS:
                old_source_ids[mid] = receipt["revision_source_id"]
            state.checkpoint(f"old-source-seal-{mid}-pass", {
                "knowledge_id": OLD_KNOWLEDGE_IDS[mid],
                "revision_source_id": receipt["revision_source_id"],
            })
        validate_old_source_ids(old_source_ids)
        state.checkpoint("all-source-seals-pass", {"source_count": 15, "provider_attempt_count": 11})
        close = teardown(runtime, failed=False)
        state.value["teardown"] = close
        if close["status"] != "STOPPED":
            state.value["status"] = "STOP_INCOMPLETE"
            state.save()
            raise RuntimeError("successful run teardown incomplete")
        state.value["status"] = "SOURCE_PASS"
        state.value["counts"] = {"uploads": 11, "provider_attempts": 11,
                                 "w1_revisions": 15, "source_seals": 15}
        state.save()
        failed = False
        print(canonical({"status": "SOURCE_PASS", "receipt": str(state.path),
                         "receipt_sha256": file_sha256(state.path)}).decode())
        return 0
    except Exception as error:
        try:
            if runtime.guard_started:
                try:
                    runtime.copy_guard_ledger(args.artifact_dir / "guard-ledger-failure.json")
                    state.value["failure_guard_ledger_sha256"] = file_sha256(
                        args.artifact_dir / "guard-ledger-failure.json")
                except Exception as ledger_error:
                    state.value["ledger_copy_error_type"] = type(ledger_error).__name__
            state.value["status"] = "STOPPED"
            state.value["error_type"] = type(error).__name__
            try:
                state.save()
            except Exception:
                pass
        finally:
            evidence = teardown(runtime, failed=True)
            state.value["teardown"] = evidence
            state.value["status"] = evidence["status"]
            try:
                state.save()
            except Exception:
                pass
        raise
    finally:
        # Best-effort local secret reference release; values were never written.
        email = password = ""


if __name__ == "__main__":
    raise SystemExit(main())
