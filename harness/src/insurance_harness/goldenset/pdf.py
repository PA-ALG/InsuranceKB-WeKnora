"""PDF → 带页码文本（spec 002 T2）。

直读原始 PDF 而非 chunk，保证证据页码与切片无关（05 §2）。
本批样本均为文本型 PDF；疑似扫描件直接报错（后续批次接 OCR 时再扩展）。
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict

_SCANNED_AVG_CHARS_THRESHOLD = 50.0


class PageText(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_no: int  # 1-based
    text: str


class ScannedPdfError(Exception):
    """疑似扫描件（平均每页可提取文本过少），当前批次不支持。"""


def detect_scanned(pages: list[PageText]) -> bool:
    if not pages:
        return True
    avg = sum(len(p.text.strip()) for p in pages) / len(pages)
    return avg < _SCANNED_AVG_CHARS_THRESHOLD


def extract_pages(pdf_path: Path) -> list[PageText]:
    import pdfplumber

    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append(PageText(page_no=i, text=text))
    if detect_scanned(pages):
        raise ScannedPdfError(
            f"{pdf_path.name}: 平均每页可提取文本 < {_SCANNED_AVG_CHARS_THRESHOLD} 字，"
            f"疑似扫描件——本批次不支持，请登记为待 OCR 样本"
        )
    return pages
