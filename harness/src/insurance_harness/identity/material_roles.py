"""Material roles recognised from data, and which whole materials may be evidence (S4i Spec §3.2).

Blueprint §7.3: roles are a few configurable types recognised automatically, never configured per
file; when unsure, quarantine. A document has a role when that role's name signal and opening-text
signal both match and no other role shows either signal. Anything else is unresolved and stops the
product, so a new or renamed material never enters evidence unseen. The name is a signal only; it is
not the source identity, which stays with the page reader.

This is a role-level veto, not field-level adoption: `evidence: true` means a material is not
vetoed. When the field x role TrustPolicy lands in catalog/, the veto becomes one of its rules and
`evidence_pages` calls its single entry point instead of this flag.
"""

import unicodedata
from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib.resources import files
from pathlib import PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

HEAD_CHARS = 200  # opening text compared, after width folding and without white space


class MaterialRoleError(ValueError):
    """A caller-safe code; never a document name or its text."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MaterialRole(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    role: str = Field(pattern=r"^[a-z][a-z_]*$")
    evidence: bool
    name_keywords: tuple[str, ...] = Field(min_length=1)
    head_keywords: tuple[str, ...] = Field(min_length=1)


class MaterialRoles(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: str = Field(min_length=1)
    roles: tuple[MaterialRole, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_roles(self) -> "MaterialRoles":
        keys = [role.role for role in self.roles]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate material role")
        return self


@lru_cache(maxsize=1)
def load_material_roles() -> MaterialRoles:
    """The roles shipped with this package."""
    try:
        text = files(__package__).joinpath("material_roles.json").read_text(encoding="utf-8")
        return MaterialRoles.model_validate_json(text)
    except (OSError, ValidationError) as error:
        raise MaterialRoleError("MATERIAL_ROLES_INVALID") from error


def _folded(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if not c.isspace())


def role_of(document: str, head: str, more: str = "") -> str | None:
    """The one role both of whose signals match while no other role shows any, else None.

    `more` is opening text read in full besides the head's first characters, such as a title line
    printed further down (S5b-7): it can only add signals, so a conflict stays a conflict.
    """
    name = _folded(PurePosixPath(document).stem)
    opening = _folded(head)[:HEAD_CHARS] + _folded(more)
    both, any_signal = [], []
    for role in load_material_roles().roles:
        by_name = any(_folded(k) in name for k in role.name_keywords)
        by_head = any(_folded(k) in opening for k in role.head_keywords)
        if by_name and by_head:
            both.append(role.role)
        if by_name or by_head:
            any_signal.append(role.role)
    return both[0] if len(both) == 1 and len(any_signal) == 1 else None


def role_signals(document: str, head: str) -> set[str]:
    """The roles that show any signal, in the name or in the opening (PV-3 Spec §2.2): a role is
    inferred from other evidence only when none does, so a conflict stays a conflict."""
    name = _folded(PurePosixPath(document).stem)
    opening = _folded(head)[:HEAD_CHARS]
    return {
        role.role
        for role in load_material_roles().roles
        if any(_folded(k) in name for k in role.name_keywords)
        or any(_folded(k) in opening for k in role.head_keywords)
    }


class _Page(Protocol):
    @property
    def document(self) -> str: ...
    @property
    def page(self) -> int: ...
    @property
    def text(self) -> str: ...


def document_roles(
    pages: Sequence[_Page], recorded: Mapping[str, str] | None = None
) -> dict[str, str | None]:
    """Each document's role: the recorded one when the registry has it (S5b-6), otherwise
    inferred from its name and its pages' text in page order. A recorded role is a confirmed,
    audited decision; inference never overrides it."""
    recorded = recorded or {}
    known = {role.role for role in load_material_roles().roles}
    if any(role not in known for role in recorded.values()):
        raise MaterialRoleError("MATERIAL_ROLE_UNKNOWN")
    texts: dict[str, list[tuple[int, str]]] = {}
    for page in pages:
        texts.setdefault(page.document, []).append((page.page, page.text))
    return {
        document: recorded.get(document)
        or role_of(document, "".join(text for _, text in sorted(numbered)))
        for document, numbered in texts.items()
    }


def evidence_pages[P: _Page](
    pages: Sequence[P], recorded: Mapping[str, str] | None = None
) -> list[P]:
    """Pages of the materials that may be evidence, in their order; one unresolved stops all."""
    evidence = {role.role: role.evidence for role in load_material_roles().roles}
    kept: set[str] = set()
    for document, role in document_roles(pages, recorded).items():
        if role is None:
            raise MaterialRoleError("MATERIAL_ROLE_UNRESOLVED")
        if evidence[role]:
            kept.add(document)
    return [page for page in pages if page.document in kept]
