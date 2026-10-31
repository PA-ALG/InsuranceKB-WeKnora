"""The rehearsal stack on its verified VM: images, generated settings, compose and the endpoint.

Every command first verifies the owned VM (vm.verify). HTTP is bound to that instance by `bind`:
the UI port comes from the ownership record, the rehearsal context's compose project must publish
exactly that loopback port, the live context must not publish it, and the endpoint must serve the
random instance marker generated at creation (mounted into this UI only). Nothing writes over HTTP
without a fresh binding. Error responses never leave `http`: callers see status codes only.
"""

import base64
import hashlib
import io
import json
import os
import re
import secrets
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import private
from vm import Runner, Settings, VmError, start, verify

PROJECT = "insurancekb-rehearsal"
HERE = Path(__file__).resolve().parent
MARKER_PATH = "/rehearsal-instance.txt"
_REF = re.compile(r"^(?:[a-z0-9][a-z0-9./_-]*@)?sha256:[0-9a-f]{64}$")
_SIGNING_RING = b"""
# Added by deploy/rehearsal: the capture/citation signing ring (Ed25519, RawURL base64).
schema_wiki_signing:
  citation_token_signing_keys:
    - key_id: rehearsal-citation-1
      private_key_base64: ${E2E_CITATION_SIGNING_KEY}
  active_citation_token_key_id: rehearsal-citation-1
"""
Opener = Callable[..., tuple[int, bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None  # a redirect is answered as its status, never followed


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def http(method: str, url: str, data: bytes | None = None,
         headers: dict[str, str] | None = None, timeout: float = 60) -> tuple[int, bytes]:
    """Status and body; an error status comes back with an empty body (R5)."""
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        error.close()
        return error.code, b""
    except (urllib.error.URLError, OSError, TimeoutError):
        return 0, b""


@dataclass(frozen=True)
class Instance:
    base: str
    instance_id: str


def marker(instance_id: str) -> bytes:
    return f"insurancekb-rehearsal {instance_id}\n".encode()


def _compose(settings: Settings, record: dict, *args: str) -> tuple[list[str], dict[str, str]]:
    argv = ["docker", "--context", settings.context, "compose", "-p", PROJECT,
            "-f", str(HERE / "compose.yaml"), "--env-file", str(settings.home / "images.env"),
            *args]
    env = {**os.environ, "REHEARSAL_HOME": str(settings.home),
           "REHEARSAL_DEFAULTS": str(HERE / "app.defaults.env"),
           "REHEARSAL_CONTRACTS_DIR": str(settings.repo / "contracts"),
           "REHEARSAL_UI_PORT": str(record["ui_port"])}
    return argv, env


def compose(settings: Settings, record: dict, run: Runner, *args: str, code: str) -> str:
    argv, env = _compose(settings, record, *args)
    done = run(argv, env=env)
    if done.returncode != 0:
        raise VmError(code)
    return done.text


def bind(settings: Settings, run: Runner, opener: Opener) -> Instance:
    """The verified rehearsal endpoint, or a refusal before any request that could write."""
    record = verify(settings, run)
    port = int(record["ui_port"])
    if port == settings.live_port:
        raise VmError("LIVE_PORT")
    argv, env = _compose(settings, record, "port", "ui", "80")
    published = run(argv, env=env)
    if published.returncode != 0 or published.text.strip() != f"127.0.0.1:{port}":
        raise VmError("ENDPOINT_NOT_REHEARSAL")
    live = run(["docker", "--context", settings.live_context, "ps", "--format", "{{.Ports}}"])
    if live.returncode != 0:
        raise VmError("LIVE_STATE_UNKNOWN")
    if re.search(rf"[:\]]{port}->", live.text):
        raise VmError("PORT_PUBLISHED_BY_LIVE")
    base = f"http://127.0.0.1:{port}"
    status, body = opener("GET", base + MARKER_PATH, None, {}, 10)
    if status != 200:
        raise VmError("INSTANCE_UNREACHABLE")
    if body != marker(record["instance_id"]):
        raise VmError("INSTANCE_MARKER_MISMATCH")
    return Instance(base=base, instance_id=record["instance_id"])


def wait_ready(settings: Settings, run: Runner, opener: Opener, attempts: int = 120) -> Instance:
    """Bind once the UI and the App behind it answer; only unreachability is retried."""
    for _ in range(attempts):
        try:
            instance = bind(settings, run, opener)
        except VmError as error:
            if error.code != "INSTANCE_UNREACHABLE":
                raise
        else:
            if opener("GET", instance.base + "/api/v1/auth/config", None, {}, 10)[0] == 200:
                return instance
        time.sleep(3)
    raise VmError("APP_UNREACHABLE")


def _lock() -> dict[str, str]:
    pairs = (line.partition("=") for line in (HERE / "images.lock").read_text().splitlines()
             if line and not line.startswith("#"))
    return {key: value for key, _, value in pairs}


def images(settings: Settings, run: Runner, source: str) -> dict:
    verify(settings, run)
    lock, refs = _lock(), {}
    target = ["docker", "--context", settings.context]
    for service in ("PG", "REDIS", "APP", "UI", "DOCREADER"):
        name = f"REHEARSAL_{service}_IMAGE"
        ref = lock.get(name) or lock.get(f"{name}_{'LIVE' if source == 'live' else 'CI'}", "")
        if not _REF.fullmatch(ref):
            raise VmError("IMAGE_REF_MISSING")
        if run([*target, "image", "inspect", ref]).returncode != 0:
            if source == "live" and service in {"APP", "UI", "DOCREADER"}:
                live = ["docker", "--context", settings.live_context]
                if run([*live, "image", "inspect", ref]).returncode != 0:
                    raise VmError("LIVE_IMAGE_MISSING")
                if run([*live, "save", ref], pipe_to=[*target, "load"]).returncode != 0:
                    raise VmError("IMAGE_COPY_FAILED")
            elif run([*target, "pull", "-q", ref]).returncode != 0:
                raise VmError("IMAGE_PULL_FAILED")
        refs[name] = ref
    home = private.private_dir(settings.home)
    private.write_env(home, "images.env", refs)
    _write_config(settings, run, refs["REHEARSAL_APP_IMAGE"])
    return {"images": len(refs), "source": source}


def _write_config(settings: Settings, run: Runner, app: str) -> None:
    """The App image's own config.yaml plus the signing ring (finding F3); no secret inside."""
    target = ["docker", "--context", settings.context]
    created = run([*target, "create", app])
    container = created.text.strip()
    if created.returncode != 0 or not re.fullmatch(r"[0-9a-f]{12,64}", container):
        raise VmError("CONFIG_READ_FAILED")
    try:
        copied = run([*target, "cp", f"{container}:/app/config/config.yaml", "-"])
    finally:
        run([*target, "rm", "-f", container])
    try:
        with tarfile.open(fileobj=io.BytesIO(copied.stdout)) as archive:
            member = archive.getmember("config.yaml")
            handle = archive.extractfile(member) if member.isreg() else None
            data = handle.read() if handle and member.size < 1 << 20 else b""
    except (tarfile.TarError, KeyError):
        data = b""
    if copied.returncode != 0 or not data:
        raise VmError("CONFIG_READ_FAILED")
    if not re.search(rb"(?m)^schema_wiki_signing:", data):
        data = data.rstrip(b"\n") + b"\n" + _SIGNING_RING
    private.write(private.private_dir(settings.home), "config.yaml", data, private.SHARED)


def _signing_key(run: Runner) -> str:
    """A Go ed25519.PrivateKey (seed || public key) in RawURL base64, made with OpenSSL."""
    generated = run(["openssl", "genpkey", "-algorithm", "ed25519", "-outform", "DER"])
    public = run(["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
                 stdin=generated.stdout)
    if generated.returncode or public.returncode or len(generated.stdout) < 32 or len(
            public.stdout) < 32:
        raise VmError("KEY_GENERATION_FAILED")
    key = generated.stdout[-32:] + public.stdout[-32:]
    return base64.urlsafe_b64encode(key).rstrip(b"=").decode()


def _valid_key(value: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))) == 64
    except ValueError:
        return False


def env(settings: Settings, run: Runner) -> dict:
    record = verify(settings, run)
    home = private.private_dir(settings.home)
    known = private.read_env(home, "secrets.env")
    for name in ("DB_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SYSTEM_AES_KEY"):
        known.setdefault(name, secrets.token_hex(16))
    if not _valid_key(known.get("E2E_CITATION_SIGNING_KEY", "")):
        known["E2E_CITATION_SIGNING_KEY"] = _signing_key(run)
    private.write_env(home, "secrets.env", known)
    app_keys = ("DB_PASSWORD", "REDIS_PASSWORD", "JWT_SECRET", "SYSTEM_AES_KEY",
                "E2E_CITATION_SIGNING_KEY")
    private.write_env(home, "app.env", {key: known[key] for key in app_keys})
    private.write_env(home, "pg.env", {"POSTGRES_USER": "weknora", "POSTGRES_DB": "weknora",
                                       "POSTGRES_PASSWORD": known["DB_PASSWORD"]})
    private.write_env(home, "redis.env", {"REDIS_PASSWORD": known["REDIS_PASSWORD"]})
    if private.read(home, "spaces.env") is None:
        private.write_env(home, "spaces.env", {})  # filled by `seed` once the KBs exist
    private.write(home, "instance-marker.txt", marker(record["instance_id"]), private.SHARED)
    return {"env": "written"}


def dns(settings: Settings, run: Runner) -> dict:
    """A fresh colima VM can boot with an inactive resolver stub; point it at its gateway."""
    verify(settings, run)
    ssh = ["colima", "ssh", "-p", settings.profile, "--"]
    if run([*ssh, "getent", "hosts", "api.deepseek.com"]).returncode == 0:
        return {"dns": "resolves"}
    route = run([*ssh, "ip", "route"])
    found = re.search(r"(?m)^default via (\d{1,3}(?:\.\d{1,3}){3}) ", route.text)
    if route.returncode != 0 or found is None:
        raise VmError("NO_DEFAULT_ROUTE")
    script = f"rm -f /etc/resolv.conf && printf 'nameserver %s\\n' {found[1]} > /etc/resolv.conf"
    if run([*ssh, "sudo", "sh", "-c", script]).returncode != 0 or run(
            [*ssh, "getent", "hosts", "api.deepseek.com"]).returncode != 0:
        raise VmError("DNS_FIX_FAILED")
    return {"dns": "gateway"}


def up(settings: Settings, run: Runner, opener: Opener) -> dict:
    start(settings, run)
    record = verify(settings, run)
    started = time.time()
    compose(settings, record, run, "up", "-d", code="COMPOSE_UP_FAILED")
    wait_ready(settings, run, opener)
    return {"healthy_seconds": round(time.time() - started)}


def recreate_app(settings: Settings, run: Runner, opener: Opener) -> Instance:
    """The App reads ENTERPRISE_SPACES and DISABLE_REGISTRATION at start."""
    record = verify(settings, run)
    compose(settings, record, run, "up", "-d", "app", code="COMPOSE_UP_FAILED")
    return wait_ready(settings, run, opener)


def ledger(settings: Settings, run: Runner) -> dict:
    record = verify(settings, run)
    query = ("select 'official', version, dirty from schema_migrations union all "
             "select 'enterprise', version, dirty from enterprise_schema_migrations")
    out = compose(settings, record, run, "exec", "-T", "pg", "psql", "-U", "weknora",
                  "-d", "weknora", "-Atc", query, code="LEDGER_UNREADABLE")
    rows = [line.split("|") for line in out.splitlines() if line.count("|") == 2]
    return {name: {"version": int(version), "dirty": dirty == "t"} for name, version, dirty in rows}


def status(settings: Settings, run: Runner) -> dict:
    record = verify(settings, run)
    services = compose(settings, record, run, "ps", "--format", "{{.Service}} {{.Status}}",
                       code="COMPOSE_PS_FAILED")
    disk = run(["colima", "ssh", "-p", settings.profile, "--", "df", "-P", "/var/lib/docker"])
    used = re.search(r"(\d+)%", disk.text.splitlines()[-1]) if disk.text.strip() else None
    return {"services": services.splitlines(), "disk_used_percent": int(used[1]) if used else None}


def down(settings: Settings, run: Runner) -> dict:
    record = verify(settings, run)
    try:
        compose(settings, record, run, "stop", code="COMPOSE_STOP_FAILED")
        if run(["colima", "stop", "-p", settings.profile], quiet=True).returncode != 0:
            raise VmError("STOP_FAILED")
    finally:
        run(["docker", "context", "use", settings.live_context])
    return {"profile": settings.profile, "state": "stopped"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def product_dir(repo: Path, product: str) -> Path:
    for meta in sorted((repo / "dataset/shouxian_product").glob("*/product_meta.json")):
        if json.loads(meta.read_text()).get("planCode") == product:
            return meta.parent
    raise VmError("PRODUCT_UNKNOWN")
