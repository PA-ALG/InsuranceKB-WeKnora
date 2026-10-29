"""Resolve a product's frozen source snapshot and declared pack from the dataset.

Golden annotation and real compilation read the same PDFs through these
functions, so a quality number always compares outputs built from one snapshot.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.catalog.trust_policy import TrustedPages, trusted_pages
from insurance_harness.eval.pdf_text import PageText, PdfReadError, pdf_pages, read_pdf
from insurance_harness.identity.material_roles import MaterialRoleError, evidence_pages

_PRODUCTS = "dataset/shouxian_product"
# Golden v2 declares the evaluated products first; v1 still declares the older ones (S4h).
_MANIFESTS = ("dataset/golden/v2/manifest.json", "dataset/golden/v1/manifest.json")


def _json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a JSON object")
    return data


def check_product_id(product_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", product_id):
        raise ValueError("invalid product identifier")


def source_directory(repo: Path, product_id: str, directory: Path | None = None) -> Path:
    """Find the one dataset folder whose product_meta.json declares this planCode."""
    if directory is None:
        matches = [
            path.parent for path in (repo / _PRODUCTS).glob("*/product_meta.json")
            if _json(path).get("planCode") == product_id
        ]
        if len(matches) != 1:
            raise ValueError("product source directory ambiguous or missing; supply --source-dir")
        directory = matches[0]
    directory = directory.resolve()
    directory.relative_to((repo / _PRODUCTS).resolve())
    return directory


@dataclass(frozen=True)
class Materials:
    """A folder's PDF pages and the roles its record confirms ({} when it records none)."""

    pages: list[PageText]
    recorded: dict[str, str]


# A folder's confirmed material roles (S12d), the dataset's counterpart of the registry's (S5b-6).
_ROLE_RECORD = "material_roles.json"


class _RecordedRole(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    role: str = Field(pattern=r"^[a-z][a-z_]*$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _RoleRecord(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    basis: str
    roles: dict[str, _RecordedRole]


def _invalid() -> MaterialRoleError:
    return MaterialRoleError("RECORDED_ROLES_INVALID")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate key")
    return dict(pairs)


def _role_record(directory: Path) -> _RoleRecord | None:
    """The folder's record, or None when it has none. A record that is there but cannot be read
    (a dangling link, a directory, unreadable or not UTF-8) is invalid, never "no record"."""
    path = directory / _ROLE_RECORD
    if not os.path.lexists(path):
        return None
    if path.is_symlink() or not path.is_file():
        raise _invalid()
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
        record = _RoleRecord.model_validate(data)
    except (OSError, ValueError) as error:  # decode, duplicate-key and validation errors
        raise _invalid() from error
    if not record.basis.strip():
        raise _invalid()
    return record


def _unreadable() -> MaterialRoleError:
    """A file that cannot be read or parsed; never the engine's message or the bytes."""
    return MaterialRoleError("MATERIAL_UNREADABLE")


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise _unreadable() from error


def _parse(name: str, content: bytes) -> list[PageText]:
    try:
        return pdf_pages(name, content)
    except PdfReadError as error:
        raise _unreadable() from error


def _read_file(path: Path) -> list[PageText]:
    try:
        return read_pdf(path)
    except (OSError, PdfReadError) as error:
        raise _unreadable() from error


def read_materials(directory: Path) -> Materials:
    """Every page of every PDF material, before roles are judged, with the folder's record.

    A record is all or nothing: it names every PDF the folder really holds (any extension case),
    so leaving a brochure out is a recorded decision rather than a missing file, and each role
    holds only for the bytes it was confirmed for. Each file is read once and its bytes are
    checked against the record before they are parsed. Whether a role exists is judged where
    roles are applied (MATERIAL_ROLE_UNKNOWN). Without a record, `*.pdf` files read as before.
    """
    record = _role_record(directory)
    if record is None:
        paths = sorted(directory.glob("*.pdf"))
        if not paths:
            raise ValueError("no source PDFs")
        return Materials([page for path in paths for page in _read_file(path)], {})
    try:
        entries = [entry for entry in directory.iterdir() if entry.suffix.lower() == ".pdf"]
    except OSError as error:
        raise _unreadable() from error
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise _invalid()
    if {entry.name for entry in entries} != set(record.roles):
        raise _invalid()
    pages: list[PageText] = []
    for entry in sorted(entries):
        content = _read_bytes(entry)
        if hashlib.sha256(content).hexdigest() != record.roles[entry.name].sha256:
            raise MaterialRoleError("MATERIAL_IDENTITY_MISMATCH")
        pages.extend(_parse(entry.name, content))
    return Materials(pages, {name: item.role for name, item in record.roles.items()})


def material_pages(directory: Path) -> list[PageText]:
    """Every page of every PDF material, before roles are judged."""
    return read_materials(directory).pages


def source_pages(directory: Path) -> list[PageText]:
    """Pages of the materials that may be evidence (S4i: rate tables are not; any unresolved
    material raises MaterialRoleError, a ValueError, so the product stops)."""
    materials = read_materials(directory)
    pages = evidence_pages(materials.pages, materials.recorded)
    if not any(page.text.strip() for page in pages):
        raise ValueError("no source page text")
    return pages


def trusted_source_pages(directory: Path) -> TrustedPages[PageText]:
    """The same frozen PDFs, with whole evidence and restricted headers kept separate."""
    materials = read_materials(directory)
    pages = trusted_pages(materials.pages, materials.recorded)
    if not any(
        page.text.strip()
        for group in [pages.evidence, *pages.table_headers.values()]
        for page in group
    ):
        raise ValueError("no source page text")
    return pages


# Packs of products outside Golden, ruled by the filed product type (S5a); versioned data.
_PRODUCT_PACKS = "dataset/product_packs.json"


def _data_file_pack(repo: Path, product_id: str) -> str | None:
    path = repo / _PRODUCT_PACKS
    if not path.is_file():
        return None
    data = _json(path)
    packs = data.get("packs")
    version = data.get("version")
    if (
        not isinstance(version, str)
        or not version.strip()
        or not isinstance(packs, dict)
        or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in packs.items())
    ):
        raise ValueError("product pack declarations are malformed")
    value = packs.get(product_id)
    return value if isinstance(value, str) else None


def declared_pack(repo: Path, product_id: str, pack_id: str | None = None) -> str:
    if pack_id is not None:
        return pack_id
    declared = _data_file_pack(repo, product_id)
    for manifest in _MANIFESTS:
        if not (repo / manifest).is_file():
            continue
        metadata = _json(repo / manifest).get("products", {}).get(product_id, {})
        value = metadata.get("pack_id") if isinstance(metadata, dict) else None
        if isinstance(value, str):
            if declared is not None and declared != value:
                raise ValueError("pack declarations disagree")
            return value
    if declared is not None:
        return declared
    raise ValueError("pack is not declared; supply --pack")


def display_name(directory: Path) -> str:
    """The filed clause name binds candidate entities to product IDs in reports."""
    value = _json(directory / "product_meta.json").get("clauseName")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("product_meta.json lacks clauseName")
    return value
