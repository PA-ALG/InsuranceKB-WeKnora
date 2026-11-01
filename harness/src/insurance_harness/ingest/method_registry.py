"""The methods section of a v2 registry: method identities and source links (SK-2 Spec §2.1).

A method is identified once, by the folded name it was first admitted under (SK-0 §2.1): its ID
never changes, names and aliases only accumulate, and every source is a link to a material-level
method-use record (SK-1) with the blocks the method rests on, a subset of the record's blocks.
Whether a link is valid is never stored: it follows the record's state, so a material invalidated
on the material side (SK-1) drops out of the method at its next compile (SK-0 §4.3 (d)). Possible
duplicates are a note for people, never a merge.
"""

import hashlib
from collections import Counter
from collections.abc import Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from insurance_harness.identity.method_signals import Block
from insurance_harness.identity.versions import normal_clause_code
from insurance_harness.ingest.method_use_model import MethodUse

MethodId = Annotated[str, StringConstraints(pattern=r"^sm-[0-9a-f]{24}$")]
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_Name = Annotated[str, StringConstraints(pattern=r"\S")]


def method_key(name: str) -> str:
    """The form names are compared in: folded as clause codes are (PV-1 §2.2), then casefolded."""
    return normal_clause_code(name).casefold()


def method_id_for(key: str) -> str:
    return "sm-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def block_order(block: str) -> tuple[int, int]:
    """A block ID (`P<page>S<n>`) as its reading position."""
    page, _, segment = block[1:].partition("S")
    return int(page), int(segment)


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class MethodLink(_Strict):
    """One material a method rests on: its source revision and the blocks that show the method."""

    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    sha256: _Digest
    block_ids: tuple[Block, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self) -> "MethodLink":
        if list(self.block_ids) != sorted(set(self.block_ids), key=block_order):
            raise ValueError("blocks are listed once, in reading order")
        return self

    @property
    def triple(self) -> tuple[str, int, str]:
        return (self.knowledge_id, self.parse_attempt, self.sha256)


class MethodEntry(_Strict):
    method_id: MethodId
    method_key: str = Field(min_length=1)
    names: tuple[_Name, ...] = Field(min_length=1)  # the canonical name first, then merged ones
    aliases: tuple[_Name, ...] = ()
    links: tuple[MethodLink, ...] = ()
    suppressed: bool = False  # withdrawn by a person (SK-2b): never compiled again
    possible_duplicates: tuple[MethodId, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> "MethodEntry":
        if self.method_key != method_key(self.names[0]):
            raise ValueError("the key is the canonical name's")
        if self.method_id != method_id_for(self.method_key):
            raise ValueError("the ID is derived from the key")
        triples = [(link.knowledge_id, link.parse_attempt) for link in self.links]
        if triples != sorted(set(triples)):
            raise ValueError("one link per source revision, in order")
        duplicates = list(self.possible_duplicates)
        if duplicates != sorted(set(duplicates)) or self.method_id in duplicates:
            raise ValueError("possible duplicates are other methods, listed once in order")
        return self

    def keys(self) -> list[str]:
        """The keys of every name and alias: the identities a candidate is looked up by."""
        return [method_key(name) for name in (*self.names, *self.aliases)]


def check_methods(methods: Sequence[MethodEntry], uses: Sequence[MethodUse]) -> None:
    """The registry-wide rules (Spec §2.1), raised as ValueError for the model validator."""
    ids = [method.method_id for method in methods]
    if ids != sorted(set(ids)):
        raise ValueError("methods are listed once, by ID")
    keys = Counter(key for method in methods for key in method.keys())
    if "" in keys or any(count > 1 for count in keys.values()):
        raise ValueError("a blank name, or a name or alias of two methods")
    records = {use.triple: use for use in uses}
    for method in methods:
        for link in method.links:
            record = records.get(link.triple)
            if record is None:
                raise ValueError("a link to no method-use record")
            if not set(link.block_ids) <= set(record.block_ids):
                raise ValueError("a link to blocks its record does not hold")
    noted = {(m.method_id, other) for m in methods for other in m.possible_duplicates}
    if any(other not in ids or (other, method) not in noted for method, other in noted):
        raise ValueError("a possible duplicate is noted on both methods")


def valid_links(method: MethodEntry, uses: Sequence[MethodUse]) -> tuple[MethodLink, ...]:
    """The links whose record is in force: active (a record being relabelled still is)."""
    active = {use.triple for use in uses if use.state == "active"}
    return tuple(link for link in method.links if link.triple in active)
