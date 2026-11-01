"""Admitting discovered method candidates into the registry's methods section (SK-2 Spec §3).

Discovery (SK-2b) reads copies of the materials in a separate knowledge base and names candidate
methods with the blocks of the original material they rest on. Admission checks each candidate on
its own, mapping the copy back to the original revision (same bytes, an active method-use record,
blocks the record holds); the copy itself never goes further. A candidate that passes is merged
into the method its name identifies, or becomes a new method; possible duplicates are noted for
people and never merged. Admission only adds: names, aliases, links and blocks are never removed,
and admitting the same candidates again changes nothing.
"""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from insurance_harness.ingest.method_registry import (
    MethodEntry,
    MethodLink,
    block_order,
    method_id_for,
    method_key,
)
from insurance_harness.ingest.method_use_model import MethodUse

CONTRACT: Literal["method-candidates.v1"] = "method-candidates.v1"
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
DUPLICATE_MIN_CHARS = 4  # a shorter contained key ("促成") says nothing about sameness


class AdmissionError(ValueError):
    """A caller-safe code; never the file path or its content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class CopyEntry(_Strict):
    """One copy in the discovery knowledge base and the original revision it was made from."""

    copy_knowledge_id: _Identifier
    copy_sha256: _Digest
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest


class Candidate(_Strict):
    name: str  # checked per candidate (NAME_INVALID), so one bad name never refuses the file
    aliases: tuple[str, ...] = ()
    copy_knowledge_id: _Identifier
    block_ids: tuple[str, ...]


class CandidateFile(_Strict):
    contract: Literal["method-candidates.v1"]
    discovery_kb_id: _Identifier
    copies: tuple[CopyEntry, ...]
    candidates: tuple[Candidate, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_candidates(path: Path) -> CandidateFile:
    """A repeated JSON key is refused first: parsing would otherwise keep only the last one."""
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text, object_pairs_hook=_unique_object)
        return CandidateFile.model_validate_json(text)
    except (OSError, UnicodeDecodeError, ValueError, ValidationError, RecursionError):
        raise AdmissionError("CANDIDATES_INVALID") from None


@dataclass(frozen=True)
class Admission:
    methods: tuple[MethodEntry, ...]  # the whole methods section after admission, by ID
    dropped: dict[str, int]  # candidates refused, by code
    created: tuple[str, ...]
    merged: tuple[str, ...]  # existing methods a candidate was merged into
    duplicates: tuple[tuple[str, str], ...]  # pairs newly noted as possible duplicates


def _checked(
    item: Candidate, copies: Sequence[CopyEntry], active: dict[tuple[str, int, str], MethodUse]
) -> MethodLink | str:
    """The original revision and blocks a candidate rests on, or why it is refused (§3.1)."""
    mapped = [copy for copy in copies if copy.copy_knowledge_id == item.copy_knowledge_id]
    if len(mapped) != 1:
        return "COPY_UNMAPPED"
    copy = mapped[0]
    if copy.copy_sha256 != copy.sha256:
        return "COPY_MISMATCH"
    record = active.get((copy.knowledge_id, copy.parse_attempt, copy.sha256))
    if record is None:
        return "METHOD_USE_NOT_ACTIVE"
    blocks = set(item.block_ids)
    if not blocks or not blocks <= set(record.block_ids):
        return "BLOCKS_OUTSIDE_RECORD"
    if not method_key(item.name) or not all(method_key(alias) for alias in item.aliases):
        return "NAME_INVALID"
    return MethodLink(
        knowledge_id=copy.knowledge_id,
        parse_attempt=copy.parse_attempt,
        sha256=copy.sha256,
        block_ids=tuple(sorted(blocks, key=block_order)),
    )


class _Book:
    """The methods section being admitted into, with every name's and alias's owner."""

    def __init__(self, methods: Sequence[MethodEntry]) -> None:
        self.entries = {method.method_id: method for method in methods}
        self.owner = {key: method.method_id for method in methods for key in method.keys()}
        self.noted: list[tuple[str, str]] = []

    def place(self, item: Candidate, link: MethodLink) -> tuple[str, bool]:
        """The method a candidate lands in (Spec §3.2), and whether it is new."""
        owner = self.owner.get(method_key(item.name))
        if owner is not None:  # the name decides
            self._merge(owner, (), item.aliases, link)
            return owner, False
        hit = sorted({self.owner[k] for k in map(method_key, item.aliases) if k in self.owner})
        if len(hit) == 1:
            self._merge(hit[0], (item.name,), item.aliases, link)
            return hit[0], False
        key = method_key(item.name)
        method_id = method_id_for(key)
        self.entries[method_id] = MethodEntry(
            method_id=method_id, method_key=key, names=(item.name.strip(),), links=(link,)
        )
        self.owner[key] = method_id
        self._merge(method_id, (), item.aliases, None)
        for other in hit:
            self._note(method_id, other)
        self._contained(method_id)
        return method_id, True

    def _merge(
        self,
        method_id: str,
        names: Sequence[str],
        aliases: Sequence[str],
        link: MethodLink | None,
    ) -> None:
        """Names and aliases whose key is free are added; one owned by another method notes it."""
        added: dict[str, list[str]] = {"names": [], "aliases": []}
        for field, values in (("names", names), ("aliases", aliases)):
            for value in values:
                owner = self.owner.get(method_key(value))
                if owner is None:
                    self.owner[method_key(value)] = method_id
                    added[field].append(value.strip())
                elif owner != method_id:
                    self._note(method_id, owner)
        method = self.entries[method_id]
        links = list(method.links) if link is None else _linked(method.links, link)
        self.entries[method_id] = method.model_copy(
            update={
                "names": (*method.names, *added["names"]),
                "aliases": (*method.aliases, *added["aliases"]),
                "links": tuple(links),
            }
        )

    def _contained(self, method_id: str) -> None:
        keys = self.entries[method_id].keys()
        for other, method in self.entries.items():
            if other != method_id and any(
                min(len(a), len(b)) >= DUPLICATE_MIN_CHARS and (a in b or b in a)
                for a in keys
                for b in method.keys()
            ):
                self._note(method_id, other)

    def _note(self, a: str, b: str) -> None:
        for one, other in ((a, b), (b, a)):
            method = self.entries[one]
            if other not in method.possible_duplicates:
                noted = tuple(sorted({*method.possible_duplicates, other}))
                self.entries[one] = method.model_copy(update={"possible_duplicates": noted})
                if one == a:
                    self.noted.append((min(a, b), max(a, b)))


def _linked(links: Sequence[MethodLink], link: MethodLink) -> list[MethodLink]:
    """The links with `link` added: blocks are joined with those already linked for its revision."""
    out = [item for item in links if item.triple != link.triple]
    blocks = {block for item in links if item.triple == link.triple for block in item.block_ids}
    joined = tuple(sorted(blocks | set(link.block_ids), key=block_order))
    out.append(link.model_copy(update={"block_ids": joined}))
    return sorted(out, key=lambda item: (item.knowledge_id, item.parse_attempt))


def admit(
    methods: Sequence[MethodEntry], uses: Sequence[MethodUse], candidates: CandidateFile
) -> Admission:
    """Every candidate in file order, each seeing the methods the earlier ones left."""
    active = {use.triple: use for use in uses if use.state == "active"}
    book = _Book(methods)
    dropped: Counter[str] = Counter()
    created: list[str] = []
    merged: list[str] = []
    for item in candidates.candidates:
        link = _checked(item, candidates.copies, active)
        if isinstance(link, str):
            dropped[link] += 1
            continue
        method_id, new = book.place(item, link)
        (created if new else merged).append(method_id)
    # model_copy skips validation: each entry is checked once more as it is now.
    entries = [MethodEntry.model_validate_json(m.model_dump_json()) for m in book.entries.values()]
    return Admission(
        methods=tuple(sorted(entries, key=lambda m: m.method_id)),
        dropped=dict(sorted(dropped.items())),
        created=tuple(created),
        merged=tuple(dict.fromkeys(m for m in merged if m not in created)),
        duplicates=tuple(sorted(set(book.noted))),
    )
