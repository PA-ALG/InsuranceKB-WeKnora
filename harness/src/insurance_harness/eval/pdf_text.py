"""Extract immutable page text from PDF bytes for offline compilation and evaluation.

Uses pdfium, the engine behind WeKnora's native PDF parse: the S4d ablations found
pdfplumber interleaves margin headings and two-column tables into body text, and the
blueprint (§7.1) does not carry pdfplumber forward. When S4c serves page text from
WeKnora's parse artifact, only the caller of this module changes.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

# pypdfium2 is installed and version-locked through pdfplumber (see uv.lock). It is not
# declared directly because the 020 admission binds the lockfile bytes; declare it when S7
# removes pdfplumber.
import pypdfium2 as pdfium


@dataclass(frozen=True)
class PageText:
    document: str
    document_sha256: str
    page: int
    text: str


class PdfReadError(ValueError):
    """Bytes pdfium cannot read; caller-safe, never the bytes or the engine's message."""

    def __init__(self) -> None:
        super().__init__("PDF_UNREADABLE")


def pdf_pages(document_name: str, content: bytes) -> list[PageText]:
    """Hash and parse this one byte snapshot; preserve empty pages and physical numbering."""
    digest = hashlib.sha256(content).hexdigest()
    try:
        document = pdfium.PdfDocument(content)
    except pdfium.PdfiumError as error:
        raise PdfReadError() from error
    try:
        pages = []
        for number in range(len(document)):
            textpage = document[number].get_textpage()
            text = textpage.get_text_range()
            pages.append(PageText(document_name, digest, number + 1, text))
        return pages
    except pdfium.PdfiumError as error:
        raise PdfReadError() from error
    finally:
        document.close()


def read_pdf(path: Path) -> list[PageText]:
    """Read the file once and parse exactly those bytes."""
    return pdf_pages(path.name, path.read_bytes())
