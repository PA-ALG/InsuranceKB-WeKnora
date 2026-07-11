"""spec 002 T2：PDF → 带页码文本（用仓库内真实样本）。"""

import pytest

from insurance_harness.goldenset import PageText, extract_pages
from insurance_harness.goldenset.pdf import detect_scanned

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
