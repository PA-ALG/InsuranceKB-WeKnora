"""模板抽取 fast path 子包（006；spec F1~F5；设计 11 §1、12 #1/#2/#4）。

- ``models``/``loader``：模板 schema（YAML 数据）与注册表（机制对齐 schemas G1）；
- ``induce``：模板归纳器（金标副产品，确定性，零模型）+ ``polish`` 润色 stub；
- ``fastpath``：运行时锚点定位与确定性抽取（走既有校验链）；
- ``tables``：表格结构识别 provider（pdfplumber 首实现，PP-StructureV3 留接口）。
"""

from .fastpath import run_fastpath
from .induce import (
    InductionError,
    InductionFieldReport,
    InductionResult,
    ProductDocInput,
    induce_template,
    render_induction_report,
)
from .loader import (
    TemplateLoadError,
    dump_template_yaml,
    load_template_registry,
    parse_template,
)
from .models import (
    ExtractionTemplate,
    FewShot,
    FieldAnchors,
    InducedFrom,
    TableAnchor,
    TemplateField,
    TemplateRegistry,
)
from .polish import PolishRequest, apply_polish, write_polish_queue
from .tables import (
    PdfplumberTableProvider,
    PPStructureV3Provider,
    TableGrid,
    TableStructureProvider,
    distinct_single_line_cells,
    select_table_provider,
)

__all__ = [
    "ExtractionTemplate",
    "FewShot",
    "FieldAnchors",
    "InducedFrom",
    "InductionError",
    "InductionFieldReport",
    "InductionResult",
    "PPStructureV3Provider",
    "PdfplumberTableProvider",
    "PolishRequest",
    "ProductDocInput",
    "TableAnchor",
    "TableGrid",
    "TableStructureProvider",
    "TemplateField",
    "TemplateLoadError",
    "TemplateRegistry",
    "apply_polish",
    "distinct_single_line_cells",
    "dump_template_yaml",
    "induce_template",
    "load_template_registry",
    "parse_template",
    "render_induction_report",
    "run_fastpath",
    "select_table_provider",
    "write_polish_queue",
]
