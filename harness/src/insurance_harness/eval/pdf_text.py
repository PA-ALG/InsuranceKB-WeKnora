"""Extract immutable page text from PDF bytes for offline compilation and evaluation.

Uses pdfium, the engine behind WeKnora's native PDF parse: the S4d ablations found
pdfplumber interleaves margin headings and two-column tables into body text, and the
blueprint (§7.1) does not carry pdfplumber forward. When S4c serves page text from
WeKnora's parse artifact, only the caller of this module changes.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium


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
    document = pdfium.PdfDocument(content)
    try:
        pages = []
        for number in range(len(document)):
            textpage = document[number].get_textpage()
            text = textpage.get_text_range().replace("\r\n", "\n").replace("\r", "\n")
            pages.append(PageText(path.name, digest, number + 1, text))
        return pages
    finally:
        document.close()
