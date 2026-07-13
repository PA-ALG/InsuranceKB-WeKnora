"""spec F5：表格结构识别 provider（协议、pdfplumber 实现、PP-StructureV3 配置位）。"""

from pathlib import Path

import pytest

from insurance_harness.compiler.templates import (
    PdfplumberTableProvider,
    PPStructureV3Provider,
    TableGrid,
    distinct_single_line_cells,
    select_table_provider,
)

DATASET = Path(__file__).resolve().parents[2] / "dataset/shouxian_product"
RATE_PDF = DATASET / "平安盛世金越（尊享版26）终身寿险" / "费率表.pdf"

GRID = TableGrid(
    rows=(
        ("交费期间\n投保年龄", "趸交", "3年", "6年", "3年"),
        ("0", "11389", "3943", "1979", "3943"),
        ("1", "11390", "3943", "1979", "3943"),
    )
)


def test_f5_1_header_row_and_cell_lookup_on_grid() -> None:
    header = GRID.header_row("趸交")
    assert header is not None and "3年" in header
    assert GRID.header_row("不存在的列") is None
    # 列定位直取（12 #1）：行键 + 列名 → 单元格
    assert GRID.lookup_cell("趸交", "3年", "0") == "3943"
    assert GRID.lookup_cell("趸交", "6年", "1") == "1979"
    assert GRID.lookup_cell("趸交", "3年", "999") is None
    assert GRID.lookup_cell("趸交", "不存在", "0") is None


def test_f5_1_distinct_single_line_cells() -> None:
    # 跨列合并头（含换行）与重复列名去除，顺序保留
    assert distinct_single_line_cells(GRID.rows[0]) == ["趸交", "3年", "6年"]
    assert distinct_single_line_cells(("", "a", "", "a", "b")) == ["a", "b"]


def test_f5_2_pdfplumber_provider_on_real_rate_table() -> None:
    if not RATE_PDF.exists():
        pytest.skip(f"样本缺失：{RATE_PDF}")
    provider = PdfplumberTableProvider()
    grids = provider.extract_tables(RATE_PDF, 1)
    assert grids, "费率表第 1 页必须能抽出表格"
    header = next((g.header_row("趸交") for g in grids if g.header_row("趸交")), None)
    assert header is not None
    assert distinct_single_line_cells(header) == ["趸交", "3年", "6年", "10年", "15年", "20年"]
    # 数字列定位直取（12 #1）：0 岁 3 年交保费
    value = next(
        (v for g in grids if (v := g.lookup_cell("趸交", "3年", "0")) is not None), None
    )
    assert value == "3943"
    # 越界页/缺文件 → 空表，不抛错（fast path 降级语义）
    assert provider.extract_tables(RATE_PDF, 999) == []
    assert provider.extract_tables(RATE_PDF.parent / "不存在.pdf", 1) == []


def test_f5_3_pp_structure_v3_stub_and_selection() -> None:
    with pytest.raises(NotImplementedError, match="HANDOFF"):
        PPStructureV3Provider()
    assert isinstance(select_table_provider("pdfplumber"), PdfplumberTableProvider)
    assert isinstance(select_table_provider(), PdfplumberTableProvider)
    with pytest.raises(NotImplementedError):
        select_table_provider("pp-structure-v3")
    with pytest.raises(ValueError, match="未知表格结构 provider"):
        select_table_provider("mineru")
