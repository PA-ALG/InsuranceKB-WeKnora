"""I3a rehearsal safety (PR #480 review R3, R5, R6): bound endpoint, fixed errors, materials.

Offline: WeKnora is a fake opener that records every request; docker is a fake runner. A local
HTTP server on 127.0.0.1 checks that error bodies never leave `stack.http`.
"""

from __future__ import annotations

import hashlib
import http.server
import importlib
import json
import re
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

DEPLOY = Path(__file__).resolve().parents[3] / "deploy/rehearsal"
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))
private: Any = importlib.import_module("private")
vm: Any = importlib.import_module("vm")
stack: Any = importlib.import_module("stack")
seed: Any = importlib.import_module("seed")
rehearsal: Any = importlib.import_module("rehearsal")

BASE, INSTANCE, TENANT = "http://127.0.0.1:18495", "a" * 32, 10000
TOKEN = "owner-session-token-SECRET-7f3a"
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


class Platform:
    """The WeKnora endpoints the seed uses, recording (method, path) of every request."""

    def __init__(self) -> None:
        self.registered = False
        self.keys: list[dict[str, Any]] = []
        self.models: list[dict[str, Any]] = []
        self.kbs: list[dict[str, Any]] = []
        self.knowledge: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str]] = []
        self.overrides: dict[tuple[str, str], tuple[int, bytes]] = {}

    @staticmethod
    def ok(document: Any, status: int = 200) -> tuple[int, bytes]:
        return status, json.dumps(document).encode()

    def __call__(self, method: str, url: str, data: bytes | None = None,
                 headers: dict[str, str] | None = None, timeout: float = 60) -> tuple[int, bytes]:
        path = url.removeprefix(BASE).split("?")[0]
        self.requests.append((method, path))
        if (method, path) in self.overrides:
            return self.overrides[(method, path)]
        body = json.loads(data) if data and not path.endswith("/file") else None
        if path == stack.MARKER_PATH:
            return 200, stack.marker(INSTANCE)
        if path == "/api/v1/auth/login":
            if not self.registered:
                return 401, b""
            return self.ok({"token": TOKEN, "tenant": {"id": TENANT}})
        if path == "/api/v1/auth/register":
            self.registered = True
            return self.ok({}, 201)
        if path == f"/api/v1/tenants/{TENANT}/api-keys":
            if method == "GET":
                return self.ok({"data": self.keys})
            self.keys.append({"id": len(self.keys) + 1})
            return self.ok({"data": {"id": len(self.keys), "token": "sk-service-key"}}, 201)
        if path == "/api/v1/models":
            if method == "GET":
                return self.ok({"data": self.models})
            assert body is not None
            self.models.append({"id": f"m{len(self.models)}", "name": body["name"],
                                "type": body["type"], "tenant_id": TENANT})
            return self.ok({"data": self.models[-1]}, 201)
        if path.startswith("/api/v1/agents/"):
            return self.ok({})
        if path == "/api/v1/knowledge-bases":
            if method == "GET":
                return self.ok({"data": self.kbs})
            assert body is not None
            self.kbs.append({"id": f"kb{len(self.kbs)}", "name": body["name"],
                             "tenant_id": TENANT})
            return self.ok({"data": self.kbs[-1]}, 201)
        if path.endswith("/knowledge/file"):
            assert data is not None
            name = re.search(rb'filename="([^"]+)"', data)
            content = data.split(b"Content-Type: application/pdf\r\n\r\n", 1)[1].rsplit(
                b"\r\n--", 1)[0]
            assert name is not None
            return self.ok({"data": self.add(name[1].decode(), content)})
        if path.endswith("/knowledge"):
            return self.ok({"data": self.knowledge, "total": len(self.knowledge)})
        return 404, b""

    def add(self, file_name: str, content: bytes) -> dict[str, Any]:
        item = {"id": f"k{len(self.knowledge)}", "file_name": file_name,
                "file_sha256": hashlib.sha256(content).hexdigest(),
                "parse_status": "completed", "current_parse_attempt": 1}
        self.knowledge.append(item)
        return item

    def writes(self, *paths: str) -> list[tuple[str, str]]:
        return [(m, p) for m, p in self.requests if m in WRITES and any(x in p for x in paths)]


def dataset(repo: Path, product: str, salt: str) -> Path:
    folder = repo / "dataset/shouxian_product" / f"product-{product}"
    folder.mkdir(parents=True)
    (folder / "product_meta.json").write_text(json.dumps({"planCode": product}))
    for name in ("保险条款.pdf", "产品说明书.pdf", "费率表.pdf"):
        (folder / name).write_bytes(f"%PDF-1.4 {product} {salt} {name}".encode())
    return folder


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope-test")
    resolved = tmp_path.resolve()
    dataset(resolved / "repo", "A", "first")
    dataset(resolved / "repo", "B", "second")
    return resolved


def context(root: Path, platform: Platform, product: str = "A") -> Any:
    home = private.private_dir(root / "home")
    settings = vm.Settings(home=home, profile="rehearsal", disk_root=None,
                           colima_home=root / "colima", live_context="colima", live_port=18295,
                           ui_port=18495, product=product, repo=root / "repo")
    return seed.Context(settings, None, platform, stack.Instance(BASE, INSTANCE), home)


def stopped(error: pytest.ExceptionInfo[Exception]) -> str:
    return str(error.value.code)  # type: ignore[attr-defined]


# R3: every HTTP write goes to the verified rehearsal instance only.

class Docker:
    def __init__(self, published: str = "127.0.0.1:18495", live: str = "", live_rc: int = 0):
        self.published, self.live, self.live_rc = published, live, live_rc

    def __call__(self, argv: list[str], **_: Any) -> Any:
        if argv[-3:] == ["port", "ui", "80"]:
            return vm.Result(0, f"{self.published}\n".encode())
        if argv[:3] == ["docker", "--context", "colima"]:
            return vm.Result(self.live_rc, self.live.encode())
        return vm.Result(0)


@pytest.fixture
def owned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stack, "verify", lambda settings, run: {
        "ui_port": 18495, "instance_id": INSTANCE})


@pytest.mark.parametrize(("docker", "expected"), [
    (Docker(live="0.0.0.0:18495->80/tcp"), "PORT_PUBLISHED_BY_LIVE"),
    (Docker(published="127.0.0.1:18295"), "ENDPOINT_NOT_REHEARSAL"),
    (Docker(live_rc=1), "LIVE_STATE_UNKNOWN")])
def test_bind_refuses_an_endpoint_it_cannot_prove(root: Path, owned: None, docker: Docker,
                                                  expected: str) -> None:
    platform = Platform()
    with pytest.raises(vm.VmError) as error:
        stack.bind(context(root, platform).settings, docker, platform)
    assert stopped(error) == expected
    assert platform.requests == []


def test_bind_refuses_an_endpoint_without_this_instance_marker(root: Path, owned: None) -> None:
    platform = Platform()
    platform.overrides[("GET", stack.MARKER_PATH)] = (200, b"<!doctype html>")
    with pytest.raises(vm.VmError) as error:
        stack.bind(context(root, platform).settings, Docker(), platform)
    assert stopped(error) == "INSTANCE_MARKER_MISMATCH"
    assert platform.requests == [("GET", stack.MARKER_PATH)]


def test_smoke_aimed_at_the_live_port_sends_nothing(root: Path,
                                                    capsys: pytest.CaptureFixture[str]) -> None:
    platform = Platform()
    env = {"HOME": str(root), "REHEARSAL_HOME": str(root / "home"), "REHEARSAL_UI_PORT": "18295"}
    assert rehearsal.main(["smoke"], env=env, run=Docker(), opener=platform) == 2
    assert json.loads(capsys.readouterr().out) == {"stopped": "LIVE_PORT"}
    assert platform.requests == []


def test_platform_refuses_a_cached_key_of_another_tenant(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform)
    private.write_env(ctx.home, "harness.env", {
        "HARNESS_WEKNORA_API_KEY": "sk-other", "KEY_ID": "1", "INSTANCE_ID": INSTANCE,
        "TENANT_ID": "20000"})
    with pytest.raises(seed.Stop) as error:
        seed.platform(ctx)
    assert stopped(error) == "CACHED_KEY_MISMATCH"
    assert platform.writes("/models", "/knowledge-bases", "/agents") == []
    assert private.read(ctx.home, "spaces.env") is None


def test_platform_refuses_a_cached_key_this_tenant_never_issued(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform)
    private.write_env(ctx.home, "harness.env", {
        "HARNESS_WEKNORA_API_KEY": "sk-other", "KEY_ID": "99", "INSTANCE_ID": INSTANCE,
        "TENANT_ID": str(TENANT)})
    with pytest.raises(seed.Stop) as error:
        seed.platform(ctx)
    assert stopped(error) == "CACHED_KEY_MISMATCH"
    assert platform.writes("/models", "/knowledge-bases", "/agents") == []


def test_platform_refuses_a_key_that_sees_another_tenants_objects(root: Path) -> None:
    platform = Platform()
    platform.kbs.append({"id": "kb-b", "name": seed.RAW_KB, "tenant_id": 20000})
    ctx = context(root, platform)
    with pytest.raises(seed.Stop) as error:
        seed.platform(ctx)
    assert stopped(error) == "SERVICE_KEY_TENANT_MISMATCH"
    assert platform.writes("/knowledge-bases") == []
    assert private.read(ctx.home, "spaces.env") is None


def test_state_and_key_of_another_instance_are_refused(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform)
    private.write_json(ctx.home, "state.json", {"instance_id": "b" * 32, "tenant_id": TENANT})
    with pytest.raises(seed.Stop) as error:
        seed.platform(ctx)
    assert stopped(error) == "STATE_FROM_OTHER_INSTANCE"
    assert platform.requests == []


def test_platform_binds_key_and_state_to_instance_and_tenant(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform)
    assert seed.platform(ctx)["tenant_id"] == TENANT
    service = private.read_env(ctx.home, "harness.env")
    assert (service["INSTANCE_ID"], service["TENANT_ID"], service["KEY_ID"]) == (
        INSTANCE, str(TENANT), "1")
    assert private.read_json(ctx.home, "state.json")["instance_id"] == INSTANCE
    seed.platform(ctx)  # a rerun reuses the verified key and objects
    assert len(platform.keys) == 1 and len(platform.models) == 3 and len(platform.kbs) == 2


# R5: failures print fixed codes and statuses, never a response body or a secret.

def test_failure_output_never_carries_a_response_body_or_token(
        root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    platform = Platform()
    platform.registered = True
    platform.overrides[("POST", f"/api/v1/tenants/{TENANT}/api-keys")] = (
        500, json.dumps({"error": f"bad token {TOKEN}"}).encode())
    ctx = context(root, platform)
    monkeypatch.setattr(seed, "connect", lambda settings, run, opener: ctx)
    env = {"HOME": str(root), "REHEARSAL_HOME": str(ctx.home)}
    assert rehearsal.main(["seed"], env=env, run=Docker(), opener=platform) == 2
    out = capsys.readouterr().out
    assert json.loads(out) == {"stopped": "API_KEY_CREATE_FAILED", "status": 500}
    assert TOKEN not in out and "bad token" not in out


def test_unexpected_errors_report_a_fixed_code(root: Path, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    def leaking(*_: Any) -> tuple[int, bytes]:
        raise ValueError(f"sk-leaked {TOKEN}")

    ctx = context(root, Platform())
    monkeypatch.setattr(seed, "connect", lambda settings, run, opener: seed.Context(
        ctx.settings, None, leaking, ctx.instance, ctx.home))
    env = {"HOME": str(root), "REHEARSAL_HOME": str(ctx.home)}
    assert rehearsal.main(["seed"], env=env, run=Docker(), opener=leaking) == 2
    out = capsys.readouterr().out
    assert json.loads(out) == {"stopped": "RESPONSE_SHAPE_UNEXPECTED"}
    assert "leaked" not in out and TOKEN not in out


@pytest.fixture
def server() -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://example.invalid/")
            else:
                self.send_response(500)
            self.end_headers()
            self.wfile.write(f"error body {TOKEN}".encode())

        def log_message(self, *_: Any) -> None:
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_http_drops_error_bodies_and_never_follows_redirects(server: str) -> None:
    assert stack.http("GET", server + "/error") == (500, b"")
    assert stack.http("GET", server + "/redirect") == (302, b"")


# R6: materials are this product's files, bound by SHA-256, never by file name.

def test_same_named_files_of_another_upload_are_not_reused(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform, product="B")
    seed.platform(ctx)
    for name in ("保险条款.pdf", "产品说明书.pdf", "费率表.pdf"):
        platform.add(name, f"%PDF-1.4 A first {name}".encode())  # product A's content
    assert seed.materials(ctx, poll_seconds=0)["materials"] == 3
    mapped = private.read_json(ctx.home / "run", "source-map.json")["products"]["B"]
    b_digests = {hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (root / "repo/dataset/shouxian_product/product-B").glob("*.pdf")}
    assert {entry["sha256"] for entry in mapped} == b_digests
    assert {entry["knowledge_id"] for entry in mapped} == {"k3", "k4", "k5"}


def test_an_exact_file_already_uploaded_is_adopted_not_reuploaded(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform)
    seed.platform(ctx)
    adopted = platform.add("保险条款.pdf", "%PDF-1.4 A first 保险条款.pdf".encode())
    seed.materials(ctx, poll_seconds=0)
    mapped = private.read_json(ctx.home / "run", "source-map.json")["products"]["A"]
    assert adopted["id"] in {entry["knowledge_id"] for entry in mapped}
    assert len(platform.writes("/knowledge/file")) == 2


def test_switching_product_on_one_instance_is_refused(root: Path) -> None:
    platform = Platform()
    seed.platform(context(root, platform))
    seed.materials(context(root, platform), poll_seconds=0)
    with pytest.raises(seed.Stop) as error:
        seed.materials(context(root, platform, product="B"), poll_seconds=0)
    assert stopped(error) == "PRODUCT_MISMATCH"
    assert len(platform.writes("/knowledge/file")) == 3


def test_a_changed_local_file_is_refused(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform)
    seed.platform(ctx)
    seed.materials(ctx, poll_seconds=0)
    (root / "repo/dataset/shouxian_product/product-A/费率表.pdf").write_bytes(b"%PDF-1.4 new")
    with pytest.raises(seed.Stop) as error:
        seed.materials(ctx, poll_seconds=0)
    assert stopped(error) == "MATERIALS_CHANGED"


def test_a_listing_digest_that_disagrees_is_refused(root: Path) -> None:
    platform = Platform()
    ctx = context(root, platform)
    seed.platform(ctx)
    original = platform.add

    def listed_wrong(name: str, content: bytes) -> dict[str, Any]:
        item = original(name, content)
        item["file_sha256"] = "0" * 64
        return item

    platform.add = listed_wrong  # type: ignore[method-assign, assignment]
    with pytest.raises(seed.Stop) as error:
        seed.materials(ctx, poll_seconds=0)
    assert stopped(error) == "MATERIAL_DIGEST_MISMATCH"
    assert not (ctx.home / "run" / "source-map.json").exists()
