"""Resolve a product's frozen source snapshot and declared pack from the dataset.

Golden annotation and real compilation read the same PDFs through these
functions, so a quality number always compares outputs built from one snapshot.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from insurance_harness.catalog.trust_policy import TrustedPages, trusted_pages
from insurance_harness.eval.pdf_text import PageText, read_pdf
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


def material_pages(directory: Path) -> list[PageText]:
    """Every page of every PDF material, before roles are judged."""
    paths = sorted(directory.glob("*.pdf"))
    if not paths:
        raise ValueError("no source PDFs")
    return [page for path in paths for page in read_pdf(path)]


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


def recorded_roles(directory: Path, pages: Sequence[PageText]) -> dict[str, str]:
    """The roles a folder records for the PDFs just read, or {} when it records none.

    A record is all or nothing: it names every PDF in the folder, so leaving a brochure out is a
    recorded decision rather than a missing file, and each role holds only for the bytes it was
    confirmed for. Whether a role exists is judged where roles are applied (MATERIAL_ROLE_UNKNOWN).
    """
    path = directory / _ROLE_RECORD
    if not path.exists():
        return {}
    try:
        record = _RoleRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise MaterialRoleError("RECORDED_ROLES_INVALID") from error
    read = {page.document: page.document_sha256 for page in pages}
    if not record.basis.strip() or set(record.roles) != set(read):
        raise MaterialRoleError("RECORDED_ROLES_INVALID")
    if any(entry.sha256 != read[name] for name, entry in record.roles.items()):
        raise MaterialRoleError("MATERIAL_IDENTITY_MISMATCH")
    return {name: entry.role for name, entry in record.roles.items()}


def source_pages(directory: Path) -> list[PageText]:
    """Pages of the materials that may be evidence (S4i: rate tables are not; any unresolved
    material raises MaterialRoleError, a ValueError, so the product stops)."""
    raw = material_pages(directory)
    pages = evidence_pages(raw, recorded_roles(directory, raw))
    if not any(page.text.strip() for page in pages):
        raise ValueError("no source page text")
    return pages


def trusted_source_pages(directory: Path) -> TrustedPages[PageText]:
    """The same frozen PDFs, with whole evidence and restricted headers kept separate."""
    raw = material_pages(directory)
    pages = trusted_pages(raw, recorded_roles(directory, raw))
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
