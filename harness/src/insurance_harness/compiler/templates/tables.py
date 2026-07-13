"""表格结构识别 provider（006 T3；spec F5；设计 11 §2 L1 层、12 #1 列定位直取）。

- ``TableStructureProvider`` 为 Protocol：fast path / 归纳器 / 可喂性评分只依赖协议，
  可注入假 provider 单测（F5.1）；
- 首个实现 ``PdfplumberTableProvider``：零新增重依赖（pdfplumber 已在 002）；
- ``PPStructureV3Provider`` 留接口 + 配置位（F5.3）：重依赖（paddle 系）部署列
  HANDOFF ⓪-B / 006 tasks.md 遗留，就位后按同协议实现并用金标回归 A/B（11 §2）。
"""

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ...goldenset.normalize import normalize_text


class TableGrid(BaseModel):
    """一张表的行×列字符串矩阵（None 单元格归一为空串）。"""

    model_config = ConfigDict(frozen=True)

    rows: tuple[tuple[str, ...], ...]

    def header_row(self, contains: str) -> tuple[str, ...] | None:
        """首个含 ``contains``（归一化子串）单元格的行——列名锚点的表头定位。"""
        needle = normalize_text(contains)
        if not needle:
            return None
        for row in self.rows:
            if any(needle in normalize_text(cell) for cell in row if cell):
                return row
        return None

    def lookup_cell(self, header_contains: str, column: str, row_label: str) -> str | None:
        """列定位直取（12 #1）：表头行定位列，再按行键取该行该列单元格。"""
        header = self.header_row(header_contains)
        if header is None:
            return None
        col_norm = normalize_text(column)
        col_idx = next(
            (i for i, cell in enumerate(header) if cell and normalize_text(cell) == col_norm),
            None,
        )
        if col_idx is None:
            return None
        header_pos = self.rows.index(header)
        label_norm = normalize_text(row_label)
        for row in self.rows[header_pos + 1 :]:
            first = next((c for c in row if c), "")
            if normalize_text(first) == label_norm:
                return row[col_idx] if col_idx < len(row) and row[col_idx] else None
        return None


def distinct_single_line_cells(row: tuple[str, ...]) -> list[str]:
    """表头行 → 有序去重的单行列名（跳过空串与含换行的跨列合并头）。"""
    out: list[str] = []
    for cell in row:
        if cell and "\n" not in cell and cell not in out:
            out.append(cell)
    return out


class TableStructureProvider(Protocol):
    """表格结构识别协议（F5.1）：实现方只需给出某页的全部表格矩阵。"""

    def extract_tables(self, pdf_path: Path, page_no: int) -> list[TableGrid]: ...


class PdfplumberTableProvider:
    """pdfplumber 表格抽取实现（F5.2）；同一 PDF 惰性打开并按页缓存。"""

    def __init__(self) -> None:
        self._cache: dict[tuple[Path, int], list[TableGrid]] = {}

    def extract_tables(self, pdf_path: Path, page_no: int) -> list[TableGrid]:
        key = (pdf_path, page_no)
        if key not in self._cache:
            import pdfplumber

            grids: list[TableGrid] = []
            if pdf_path.exists():
                with pdfplumber.open(pdf_path) as pdf:
                    if 1 <= page_no <= len(pdf.pages):
                        for table in pdf.pages[page_no - 1].extract_tables():
                            grids.append(
                                TableGrid(
                                    rows=tuple(
                                        tuple(cell or "" for cell in row) for row in table
                                    )
                                )
                            )
            self._cache[key] = grids
        return self._cache[key]


class PPStructureV3Provider:
    """PP-StructureV3 表格结构识别（F5.3 接口预留，未部署）。

    重依赖（paddlepaddle/paddleocr）按 08 选型进程隔离部署，交接见
    HANDOFF ⓪-B 与 006 tasks.md 遗留清单；就位后实现 ``extract_tables``
    并用金标回归 A/B 验证（11 §2 解析器 A/B 机制）。
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "PP-StructureV3 provider 未部署：重依赖部署任务见 HANDOFF ⓪-B / "
            "openspec/changes/006-template-fastpath/tasks.md 遗留清单；"
            "当前请用默认 HARNESS_TABLE_PROVIDER=pdfplumber"
        )

    def extract_tables(self, pdf_path: Path, page_no: int) -> list[TableGrid]:
        raise NotImplementedError  # pragma: no cover - __init__ 已 fail fast


def select_table_provider(name: str = "pdfplumber") -> TableStructureProvider:
    """按配置位（HARNESS_TABLE_PROVIDER）选择实现；未知值 fail fast（F5.3）。"""
    if name == "pdfplumber":
        return PdfplumberTableProvider()
    if name == "pp-structure-v3":
        return PPStructureV3Provider()  # 实例化即抛 NotImplementedError
    raise ValueError(f"未知表格结构 provider：{name!r}（可用：pdfplumber / pp-structure-v3）")
