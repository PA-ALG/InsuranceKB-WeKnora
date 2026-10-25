"""A fake S5b-3a platform for the S5b-3c-2 tests (protected, written by Claude).

It keeps the rules the real one enforces: one item per (subject, revision, content), answers only
appended, an item closed once, an applied closure only for the latest answer, and the S5b-3a limits
on identifiers, text, options and the 512 KiB request body. Like the real one it stores title,
detail and labels trimmed as Go's strings.TrimSpace trims them, and refuses a batch naming one
item twice. Pages of the S5b-1 fixture are served for the command tests.
"""

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.ingest.upload_helpers import SPACE, material

_IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9:._-]{0,127}$")
_CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")
_SPACE = "[\t\n\v\f\r \u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"
_EDGES = re.compile(f"^{_SPACE}+|{_SPACE}+$")
MAX_BODY = 512 << 10


def trim(text: str) -> str:
    """Go's strings.TrimSpace (unicode.IsSpace)."""
    return _EDGES.sub("", text)


PREFIX = f"/api/v1/enterprise/spaces/{SPACE}/confirmations"


def _refuse(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"success": False, "code": code, "error": "refused"})


def _ok(data: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def _text(value: object, limit: int, required: bool) -> bool:
    """The platform checks the trimmed text: present if required, within the limit, printable."""
    if not isinstance(value, str):
        return False
    text = trim(value)
    return (bool(text) or not required) and len(text) <= limit and not _CONTROL.search(text)


class FakePlatform:
    def __init__(self, uploads: dict[str, tuple[str, str]] | None = None) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.answers: dict[str, list[dict[str, Any]]] = {}
        self.closures: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []  # paths of POST requests, in order
        self.closed: list[tuple[str, str, str | None]] = []  # (item id, reason, answer id)
        self.before_close: Callable[[str], None] | None = None
        self.fail_closures_after: int | None = None  # closures that succeed before a 503
        self.lose_closure_responses = 0  # closures performed whose 201 is replaced by a 503
        # Opening text and document SHA of uploads outside the fixture, by knowledge id.
        self.uploads = uploads or {}
        self._next = 0

    # What a person or another submitter does --------------------------------------------------

    def answer(
        self, item_id: str, option_key: str, note: str = "", answerer: str = "user:alice"
    ) -> str:
        assert item_id not in self.closures and option_key in {
            o["key"] for o in self.items[item_id]["options"]
        }
        answer_id = self._id("answer")
        self.answers.setdefault(item_id, []).append(
            {
                "id": answer_id,
                "item_id": item_id,
                "option_key": option_key,
                "note": note,
                "answerer": answerer,
                "answered_at": f"2026-10-25T10:{self._next:02d}:00Z",
            }
        )
        return answer_id

    def add(self, subject: str, revision: str, title: str, options: list[dict[str, str]]) -> str:
        return self._store(
            {
                "subject": subject,
                "revision": revision,
                "title": title,
                "detail": "",
                "options": options,
            }
        )

    def find(self, subject: str) -> list[dict[str, Any]]:
        return [self.view(i) for i, item in self.items.items() if item["subject"] == subject]

    def view(self, item_id: str) -> dict[str, Any]:
        item = dict(self.items[item_id])
        if self.answers.get(item_id):
            item["answer"] = self.answers[item_id][-1]
        if item_id in self.closures:
            item["closure"] = self.closures[item_id]
        return item

    # The HTTP surface -------------------------------------------------------------------------

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/sources/" in path:
            return self._pages(request)
        if request.method == "POST":
            self.writes.append(path)
        if path == PREFIX and request.method == "POST":
            if len(request.content) > MAX_BODY:
                return _refuse(400, "CONFIRMATION_INVALID")
            return self._submit(json.loads(request.content))
        if path == PREFIX and request.method == "GET":
            status = request.url.params.get("status")
            if status not in {"open", "closed"}:
                return _refuse(400, "CONFIRMATION_INVALID")
            listed = [
                self.view(i) for i in self.items if (i in self.closures) == (status == "closed")
            ]
            return _ok({"items": listed})
        if path.startswith(PREFIX + "/") and path.endswith("/closure") and request.method == "POST":
            return self._close(path.split("/")[-2], json.loads(request.content))
        return _refuse(404, "RELEASE_NOT_FOUND")

    def _submit(self, body: dict[str, Any]) -> httpx.Response:
        items = body.get("items")
        if (
            not isinstance(items, list)
            or not 1 <= len(items) <= 200
            or not all(self._valid(i) for i in items)
        ):
            return _refuse(400, "CONFIRMATION_INVALID")
        normal = [self._normal(item) for item in items]
        identities = [(i["subject"], i["revision"], self._digest(i)) for i in normal]
        if len(set(identities)) != len(identities):
            return _refuse(400, "CONFIRMATION_INVALID")
        return _ok({"items": [self.view(self._store(item)) for item in normal]}, 201)

    @staticmethod
    def _normal(item: dict[str, Any]) -> dict[str, Any]:
        options = [{"key": o["key"], "label": trim(o["label"])} for o in item["options"]]
        return item | {
            "title": trim(item["title"]),
            "detail": trim(item["detail"]),
            "options": options,
        }

    @staticmethod
    def _digest(item: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"detail": item["detail"], "options": item["options"], "title": item["title"]},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _valid(self, item: dict[str, Any]) -> bool:
        options = item.get("options")
        keys = [o.get("key") for o in options] if isinstance(options, list) else []
        return (
            set(item) == {"subject", "revision", "title", "detail", "options"}
            and all(
                isinstance(item[k], str) and _IDENTITY.fullmatch(item[k])
                for k in ("subject", "revision")
            )
            and _text(item["title"], 200, True)
            and _text(item["detail"], 2000, False)
            and isinstance(options, list)
            and 1 <= len(options) <= 50
            and len(set(keys)) == len(keys)
            and all(
                set(o) == {"key", "label"}
                and isinstance(o["key"], str)
                and _KEY.fullmatch(o["key"])
                for o in options
            )
            and all(_text(o["label"], 200, True) for o in options)
        )

    def _store(self, item: dict[str, Any]) -> str:
        item = self._normal(item)
        digest = self._digest(item)
        for item_id, stored in self.items.items():
            if (stored["subject"], stored["revision"], stored["content_digest"]) == (
                item["subject"],
                item["revision"],
                digest,
            ):
                return item_id
        item_id = self._id("item")
        self.items[item_id] = {
            "id": item_id,
            "space_id": SPACE,
            "subject": item["subject"],
            "revision": item["revision"],
            "content_digest": digest,
            "title": item["title"],
            "detail": item["detail"],
            "options": [dict(o) for o in item["options"]],
            "created_by": "service:harness",
            "created_at": f"2026-10-25T09:{self._next:02d}:00Z",
        }
        return item_id

    def _close(self, item_id: str, body: dict[str, Any]) -> httpx.Response:
        if self.fail_closures_after is not None and len(self.closed) >= self.fail_closures_after:
            return _refuse(503, "SERVICE_UNAVAILABLE")
        if self.before_close is not None:
            self.before_close(item_id)
        if item_id not in self.items:
            return _refuse(404, "CONFIRMATION_NOT_FOUND")
        reason, answer_id = body.get("reason"), body.get("answer_id") or None
        if set(body) - {"reason", "answer_id"} or reason not in {"applied", "obsolete"}:
            return _refuse(400, "CONFIRMATION_INVALID")
        if (reason == "applied") != (answer_id is not None):
            return _refuse(400, "CONFIRMATION_INVALID")
        if item_id in self.closures:
            return _refuse(409, "CONFIRMATION_CLOSED")
        latest = (self.answers.get(item_id) or [{}])[-1].get("id")
        if reason == "applied" and answer_id != latest:
            return _refuse(409, "ANSWER_STALE")
        closure: dict[str, Any] = {
            "reason": reason,
            "closed_by": "service:harness",
            "closed_at": "2026-10-25T11:00:00Z",
        }
        if answer_id:
            closure["answer_id"] = answer_id
        self.closures[item_id] = closure
        self.closed.append((item_id, reason, answer_id))
        if self.lose_closure_responses:
            self.lose_closure_responses -= 1
            return _refuse(503, "SERVICE_UNAVAILABLE")
        return _ok({"closure": closure}, 201)

    def _pages(self, request: httpx.Request) -> httpx.Response:
        parts = request.url.path.split("/")
        kid, attempt = parts[parts.index("sources") + 1], int(parts[parts.index("attempts") + 1])
        if kid in self.uploads:
            head, sha = self.uploads[kid]
        else:
            _, product_id, role = kid.split("-", 2)
            head, sha = material(product_id, role)["head"], material(product_id, role)["sha256"]
        texts = [head, ""]
        pages = [
            {
                "page_number": n,
                "text": t,
                "page_text_sha256": hashlib.sha256(t.encode()).hexdigest(),
            }
            for n, t in enumerate(texts, 1)
        ]
        body = {
            "knowledge_id": kid,
            "parse_attempt": attempt,
            "document": "upload.pdf",
            "document_sha256": sha,
            "parser_identity_sha256": "1" * 64,
            "native_sha256": "2" * 64,
            "pages": pages,
        }
        return httpx.Response(200, json=body)

    def _id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next:04d}"
