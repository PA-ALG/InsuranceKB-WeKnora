"""Extract immutable page text from PDF bytes for offline evidence verification."""

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pdfplumber


@dataclass(frozen=True)
class PageText:
    document: str
    document_sha256: str
    page: int
    text: str


def read_pdf(path: Path) -> list[PageText]:
    """Hash and parse the same snapshot; preserve empty pages and physical numbering."""
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    with pdfplumber.open(BytesIO(content)) as document:
        return [
            PageText(path.name, digest, number, page.extract_text() or "")
            for number, page in enumerate(document.pages, 1)
        ]
