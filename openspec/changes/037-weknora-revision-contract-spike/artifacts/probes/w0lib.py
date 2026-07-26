"""W0 spike shared library (OpenSpec 037).

Safety invariants:
- Only creates/mutates/deletes objects whose *name/title/metadata owner* carries
  the ``w0-spike-`` prefix, inside a scratch KB created by this spike.
- Pre-existing KBs/knowledge are touched read-only (listing/GET) only.
- No secret value is ever printed or persisted: tokens live in process memory;
  every JSON dump passes through ``redact``.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from stat import S_IMODE
from typing import Any

import httpx

RUNTIME_PATH = Path(
    "/Users/houjing/Documents/LLM_wiki/.worktrees/insurancekb-app-digest-writeback"
    "/.env.local-live.runtime"
)
BASE_URL = "http://127.0.0.1:8080/api/v1"
RESULTS = Path(__file__).with_name("results")
STATE_PATH = RESULTS / "state.json"

_SECRET_KEY_RE = re.compile(
    r"(api_key|token|password|secret|authorization|dsn)", re.IGNORECASE
)
# env values that must never leak into logs
_SENSITIVE_ENV_SUFFIXES = (
    "_API_KEY", "_PASSWORD", "_TOKEN", "_SECRET", "_USERNAME", "_EMAIL", "_AES_KEY",
)


def read_runtime_env(path: Path = RUNTIME_PATH) -> dict[str, str]:
    if S_IMODE(path.stat().st_mode) != 0o600:
        raise RuntimeError("runtime env file permission must be 0600")
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep:
            values[name.strip()] = value.strip()
    return values


def redact(obj: Any) -> Any:
    """Deep-copy JSON-ish object, masking values under secret-looking keys."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = "<REDACTED>"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def log_json(name: str, payload: Any) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{name}.json"
    path.write_text(json.dumps(redact(payload), indent=2, ensure_ascii=False, default=str))
    print(f"[saved] {path.name}")
    return path


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict[str, Any]) -> None:
    RESULTS.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


class Api:
    """Thin wrapper: admin bearer + scoped API-key requests, no proxy env."""

    def __init__(self) -> None:
        self.env = read_runtime_env()
        self.http = httpx.Client(base_url=BASE_URL, timeout=60.0, trust_env=False)
        self._bearer: str | None = None
        self.tenant_id: int | None = None

    # ------------------------------------------------------------- admin auth
    def admin_login(self) -> None:
        resp = self.http.post(
            "/auth/login",
            json={
                "email": self.env["WEKNORA_ADMIN_EMAIL"],
                "password": self.env["WEKNORA_ADMIN_PASSWORD"],
            },
        )
        resp.raise_for_status()
        doc = resp.json()
        token = doc.get("token")
        refresh = doc.get("refresh_token")
        if not token or not refresh:
            raise RuntimeError("login response missing token")
        self._bearer = token
        active = doc.get("active_tenant") or {}
        self.tenant_id = int(active.get("id"))
        wanted = int(self.env["LOCAL_LIVE_TENANT_ID"])
        if self.tenant_id != wanted:
            resp = self.http.post(
                "/auth/switch-tenant",
                headers=self._admin_headers(),
                json={"tenant_id": wanted, "refresh_token": refresh},
            )
            resp.raise_for_status()
            doc = resp.json()
            if isinstance(doc, dict) and "data" in doc:
                doc = doc["data"]
            self._bearer = doc["token"]
            self.tenant_id = int(doc["active_tenant"]["id"])
        assert self.tenant_id == wanted

    def _admin_headers(self) -> dict[str, str]:
        if not self._bearer:
            raise RuntimeError("admin not logged in")
        return {"Authorization": f"Bearer {self._bearer}"}

    def admin(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return self.http.request(
            method, path, headers=self._admin_headers(), json=json_body, params=params
        )

    # ------------------------------------------------------------ api-key ops
    def key_request(
        self,
        token: str,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
        files: Any | None = None,
        data: Any | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        return self.http.request(
            method,
            path,
            headers={"X-API-Key": token},
            json=json_body,
            params=params,
            files=files,
            data=data,
            timeout=timeout,
        )

    def create_api_key(
        self, name: str, kb_ids: list[str], capabilities: list[str]
    ) -> tuple[int, str]:
        resp = self.admin(
            "POST",
            f"/tenants/{self.tenant_id}/api-keys",
            json_body={
                "name": name,
                "full_access": False,
                "knowledge_base_ids": kb_ids,
                "capabilities": capabilities,
            },
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return int(data["id"]), data["token"]

    def find_api_key_token(self, key_id: int) -> str:
        resp = self.admin("GET", f"/tenants/{self.tenant_id}/api-keys")
        resp.raise_for_status()
        for item in resp.json()["data"]:
            if int(item["id"]) == key_id:
                return item["api_key"]
        raise RuntimeError(f"api key {key_id} not found")

    def close(self) -> None:
        self.http.close()


def envelope_summary(resp: httpx.Response) -> dict[str, Any]:
    """Status + JSON body (redacted upstream) for evidence logs."""
    try:
        body = resp.json()
    except Exception:
        body = {"_raw_text": resp.text[:400]}
    return {"status_code": resp.status_code, "body": body}


# ------------------------------------------------------------------ tiny PDF
def build_pdf(pages: int = 5, lines_per_page: int = 25) -> bytes:
    """Hand-built valid PDF (Helvetica, ASCII) — no external deps."""

    def esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    objects: list[bytes] = []  # 1-indexed
    font_obj = 3
    first_page_obj = 4
    page_objs = [first_page_obj + 2 * i for i in range(pages)]
    kids = " ".join(f"{n} 0 R" for n in page_objs)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode()
    )  # 2
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3
    for p in range(pages):
        content_obj = page_objs[p] + 1
        lines = []
        for i in range(lines_per_page):
            lines.append(
                f"W0 spike scratch clause p{p + 1:02d} l{i + 1:02d}: the insured "
                f"event waiting period and benefit ratio sample sentence number "
                f"{p * lines_per_page + i + 1} for revision contract probing."
            )
        stream_parts = ["BT /F1 10 Tf 40 800 Td 13 TL"]
        for line in lines:
            stream_parts.append(f"({esc(line)}) Tj T*")
        stream_parts.append("ET")
        stream = " ".join(stream_parts).encode()
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> "
                f"/Contents {content_obj} 0 R >>"
            ).encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream"
        )
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def wait_parsed(
    api: Api,
    token: str,
    knowledge_id: str,
    *,
    timeout_s: float = 300.0,
    poll_s: float = 1.0,
    accept: tuple[str, ...] = ("completed", "failed", "cancelled"),
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = api.key_request(token, "GET", f"/knowledge/{knowledge_id}")
        resp.raise_for_status()
        last = resp.json()["data"]
        if last.get("parse_status") in accept:
            return last
        time.sleep(poll_s)
    raise TimeoutError(f"parse not terminal within {timeout_s}s: {last.get('parse_status')}")


def knowledge_public_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Full public GET /knowledge/:id object minus bulky nested noise."""
    return {k: v for k, v in item.items()}


def chunk_brief(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id"),
        "seq_id": c.get("seq_id"),
        "chunk_index": c.get("chunk_index"),
        "is_enabled": c.get("is_enabled"),
        "chunk_type": c.get("chunk_type"),
        "content_hash": c.get("content_hash"),
        "content_len": len(c.get("content") or ""),
        "start_at": c.get("start_at"),
        "end_at": c.get("end_at"),
        "pre_chunk_id": c.get("pre_chunk_id"),
        "next_chunk_id": c.get("next_chunk_id"),
        "created_at": c.get("created_at"),
        "updated_at": c.get("updated_at"),
    }
