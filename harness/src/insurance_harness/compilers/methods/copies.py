"""Method materials copied into the method discovery base, and the copy mapping (SK-2b §2, §3).

Native discovery runs on copies (SK-0 §4.1): each active method-use record's material is copied
byte for byte into the discovery knowledge base, and the mapping names the original revision of
each copy. A copy is only ever made from bytes whose digest is the record's; the platform's own
digest of the copy is read again whenever candidates are made, so admission can refuse a copy that
no longer holds the original bytes. A record that is no longer active (SK-1 invalidated it) has its
copy deleted. A run reconciles before it writes: a copy the listing already holds with the
original's digest, or one the platform names as a duplicate, is taken over instead of uploaded
again, so a run that failed half way never leaves two copies of one material.
"""

import hashlib
import json
import os
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.compilers.methods.platform import PlatformCallError
from insurance_harness.ingest.method_use_model import MethodUse
from insurance_harness.ingest.raw_sources import RawListing
from insurance_harness.ingest.registry import ProductRegistry

_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# A material that cannot be read as the record's revision is skipped, not the whole run.
_SKIPPED = frozenset({"SOURCE_TOO_LARGE", "SOURCE_UNAVAILABLE"})


class CopiesError(ValueError):
    """A caller-safe code; never the file path or its content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class MethodCopy(_Strict):
    copy_knowledge_id: _Identifier
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest

    @property
    def triple(self) -> tuple[str, int, str]:
        return (self.knowledge_id, self.parse_attempt, self.sha256)


class CopyBook(_Strict):
    contract: Literal["method-copies.v1"]
    space_id: _Identifier
    discovery_kb_id: _Identifier
    copies: tuple[MethodCopy, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "CopyBook":
        ids = [copy.copy_knowledge_id for copy in self.copies]
        order = [(copy.knowledge_id, copy.parse_attempt) for copy in self.copies]
        if len(set(ids)) != len(ids) or order != sorted(set(order)):
            raise ValueError("one copy per revision and one revision per copy, in order")
        return self


def empty_book(space_id: str, discovery_kb_id: str) -> CopyBook:
    return CopyBook(contract="method-copies.v1", space_id=space_id, discovery_kb_id=discovery_kb_id)


def load_copies(path: Path, space_id: str, discovery_kb_id: str) -> CopyBook:
    """The mapping of this Space's discovery base; a missing file is an empty mapping."""
    if not path.exists():
        return empty_book(space_id, discovery_kb_id)
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text, object_pairs_hook=_unique_object)
        book = CopyBook.model_validate_json(text)
    except (OSError, UnicodeDecodeError, ValueError, ValidationError, RecursionError):
        raise CopiesError("COPIES_INVALID") from None
    if (book.space_id, book.discovery_kb_id) != (space_id, discovery_kb_id):
        raise CopiesError("COPIES_MISMATCH")
    return book


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def save_copies(book: CopyBook, path: Path) -> None:
    """Replace the file in one step: a failed write leaves the previous mapping in place."""
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(book.model_dump_json(indent=1).encode("utf-8") + b"\n")
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


class CopyPlatform(Protocol):
    def listing(self, kb_id: str) -> RawListing: ...

    def download(self, knowledge_id: str) -> bytes: ...

    def upload(self, kb_id: str, file_name: str, data: bytes) -> tuple[str, bool]: ...

    def delete(self, knowledge_id: str) -> None: ...


@dataclass(frozen=True)
class CopySync:
    book: CopyBook  # the mapping after a live run; the given one after a plan
    report: dict[str, Any]  # codes and counts only


def sync_copies(
    registry: ProductRegistry, book: CopyBook, platform: CopyPlatform, *, live: bool
) -> CopySync:
    """The discovery base brought in line with the active records (Spec §3); a plan unless live."""
    if book.discovery_kb_id == registry.raw_kb_id:
        raise CopiesError("DISCOVERY_KB_INVALID")
    if book.space_id != registry.space_id:
        raise CopiesError("COPIES_MISMATCH")
    listing = platform.listing(book.discovery_kb_id)
    listed = {source.knowledge_id for source in listing.completed}
    listed |= {source.knowledge_id for source in listing.unfinished}
    digests = {source.knowledge_id: source.sha256 for source in listing.completed}
    active = {use.triple: use for use in registry.method_uses if use.state == "active"}
    counts: Counter[str] = Counter()
    kept: list[MethodCopy] = []
    stale: list[MethodCopy] = []
    for copy in book.copies:
        if copy.copy_knowledge_id not in listed:
            counts["gone"] += 1  # deleted elsewhere: never deleted here, copied again below
        elif copy.triple in active:
            counts["kept"] += 1
            kept.append(copy)
        else:
            counts["stale"] += 1
            stale.append(copy)
    claimed = {copy.sha256 for copy in kept}
    taken = {copy.copy_knowledge_id for copy in (*kept, *stale)}
    needed: list[MethodUse] = []
    for triple, use in sorted(active.items()):
        if any(copy.triple == triple for copy in kept):
            continue
        if use.sha256 in claimed:
            counts["SAME_BYTES"] += 1  # one copy serves one revision (Spec §3)
            continue
        claimed.add(use.sha256)
        needed.append(use)
    if not live:
        counts["to_copy"] += len(needed)
        return CopySync(book, _report(counts, live))
    for copy in stale:
        platform.delete(copy.copy_knowledge_id)
    made: list[MethodCopy] = []
    for use in needed:
        outcome = _copy(use, book.discovery_kb_id, platform, digests, taken)
        if isinstance(outcome, str):
            counts[outcome] += 1
            continue
        copy, how = outcome
        counts[how] += 1
        taken.add(copy.copy_knowledge_id)
        made.append(copy)
    copies = sorted([*kept, *made], key=lambda c: (c.knowledge_id, c.parse_attempt))
    return CopySync(book.model_copy(update={"copies": tuple(copies)}), _report(counts, live))


def _copy(
    use: MethodUse,
    kb_id: str,
    platform: CopyPlatform,
    digests: dict[str, str],
    taken: set[str],
) -> tuple[MethodCopy, str] | str:
    """One record's copy: taken over from the listing, or uploaded from verified bytes."""
    listed = sorted(cid for cid, sha in digests.items() if sha == use.sha256 and cid not in taken)
    if listed:
        return _mapped(listed[0], use), "adopted"
    try:
        data = platform.download(use.knowledge_id)
    except PlatformCallError as error:
        if error.code in _SKIPPED:
            return error.code
        raise
    if hashlib.sha256(data).hexdigest() != use.sha256:
        return "SOURCE_CHANGED"  # another revision now: SK-1 judges it again first
    copy_id, created = platform.upload(kb_id, use.file_name, data)
    if copy_id in taken:
        raise PlatformCallError("UPLOAD_FAILED")  # a duplicate of another mapped copy
    return _mapped(copy_id, use), "copied" if created else "adopted"


def _mapped(copy_id: str, use: MethodUse) -> MethodCopy:
    return MethodCopy(
        copy_knowledge_id=copy_id,
        knowledge_id=use.knowledge_id,
        parse_attempt=use.parse_attempt,
        sha256=use.sha256,
    )


def _report(counts: Counter[str], live: bool) -> dict[str, Any]:
    return {"counts": dict(sorted((k, v) for k, v in counts.items() if v)), "live": live}
