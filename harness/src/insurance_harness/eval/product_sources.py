"""Resolve a product's frozen source snapshot and declared pack from the dataset.

Golden annotation and real compilation read the same PDFs through these
functions, so a quality number always compares outputs built from one snapshot.
"""

import json
import re
from pathlib import Path
from typing import Any

from insurance_harness.eval.pdf_text import PageText, read_pdf

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


def source_pages(directory: Path) -> list[PageText]:
    paths = sorted(directory.glob("*.pdf"))
    if not paths:
        raise ValueError("no source PDFs")
    pages = [page for path in paths for page in read_pdf(path)]
    if not any(page.text.strip() for page in pages):
        raise ValueError("no source page text")
    return pages


def declared_pack(repo: Path, product_id: str, pack_id: str | None = None) -> str:
    if pack_id is not None:
        return pack_id
    for manifest in _MANIFESTS:
        if not (repo / manifest).is_file():
            continue
        metadata = _json(repo / manifest).get("products", {}).get(product_id, {})
        value = metadata.get("pack_id") if isinstance(metadata, dict) else None
        if isinstance(value, str):
            return value
    raise ValueError("pack is not declared; supply --pack")


def display_name(directory: Path) -> str:
    """The filed clause name binds candidate entities to product IDs in reports."""
    value = _json(directory / "product_meta.json").get("clauseName")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("product_meta.json lacks clauseName")
    return value
