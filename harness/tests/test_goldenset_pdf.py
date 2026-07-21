"""spec 002 T2 / 020 D1.5：PDF → 带页码文本。"""

from io import BytesIO
from types import TracebackType
from typing import Self

import pdfplumber
import pytest

from insurance_harness.goldenset import PageText, extract_pages
from insurance_harness.goldenset.pdf import detect_scanned, extract_pages_bytes

from .conftest import DATASET_DIR


def test_extract_pages_real_clause_pdf() -> None:
    pdfs = sorted(DATASET_DIR.glob("*/保险条款.pdf"))
    if not pdfs:
        pytest.skip("样本语料不存在（dataset/shouxian_product）")
    pages = extract_pages(pdfs[0])
    assert pages[0].page_no == 1
    assert len(pages) > 1
    assert sum(len(p.text) for p in pages) > 1000  # 文本型 PDF，非扫描件


def test_detect_scanned_on_empty_pages() -> None:
    assert detect_scanned([]) is True
    assert detect_scanned([PageText(page_no=1, text="短")]) is True
    assert detect_scanned([PageText(page_no=1, text="长文本" * 100)]) is False


def test_d1_5_extract_pages_bytes_parses_exact_verified_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified_bytes = b"exact-signed-pdf-bytes"
    opened_payloads: list[bytes] = []

    class _Page:
        def extract_text(self) -> str:
            return "已验证的文本" * 20

    class _Pdf:
        pages = [_Page()]

        def __enter__(self) -> Self:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    def _open(stream: BytesIO) -> _Pdf:
        assert isinstance(stream, BytesIO)
        opened_payloads.append(stream.getvalue())
        return _Pdf()

    monkeypatch.setattr(pdfplumber, "open", _open)

    pages = extract_pages_bytes(verified_bytes, source_name="signed.pdf")

    assert opened_payloads == [verified_bytes]
    assert pages == [PageText(page_no=1, text="已验证的文本" * 20)]
